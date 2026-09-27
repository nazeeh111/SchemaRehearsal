"""Bounded SQLite copies and comparisons. This is not an OS security sandbox."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Limits:
    database_bytes: int = 64 * 1024 * 1024
    input_bytes: int = 1024 * 1024
    result_bytes: int = 2 * 1024 * 1024
    result_rows: int = 10_000
    seconds: float = 30


class RehearsalError(Exception):
    """A controlled diagnostic with no application values."""


def _require(condition, message):
    if not condition:
        raise RehearsalError(message)


def _keys(value, required, optional=()):
    _require(isinstance(value, dict), "Expected a JSON object.")
    _require(
        set(required) <= value.keys() and value.keys() <= set(required) | set(optional),
        "Missing or unsupported suite fields.",
    )


def _name(value):
    _require(
        isinstance(value, str)
        and 0 < len(value) <= 120
        and not any(ord(c) < 32 for c in value),
        "Names must contain 1–120 printable characters.",
    )


def _query(value, *, step, limits):
    _keys(
        value,
        ["sql"] if step else ["name", "sql"],
        ["parameters", "expect_error"] if step else ["parameters", "order"],
    )
    _require(
        isinstance(value["sql"], str)
        and 0 < len(value["sql"].encode()) <= limits.input_bytes,
        "SQL must be nonempty and within the input limit.",
    )
    params = value.get("parameters", [])
    _require(
        isinstance(params, list) and len(params) <= 100,
        "Parameters must be an array of at most 100 values.",
    )
    for p in params:
        _require(
            p is None or type(p) in (str, int, float),
            "Parameters support null, string, integer or finite real values.",
        )
        if type(p) is int:
            _require(
                -(2**63) <= p < 2**63,
                "Integer parameter is outside SQLite signed 64-bit range.",
            )
        if type(p) is float:
            _require(math.isfinite(p), "Real parameters must be finite.")
    if step and "expect_error" in value:
        _require(
            isinstance(value["expect_error"], str)
            and value["expect_error"] in CONSTRAINT_NAMES,
            "Expected errors must name an SQLite constraint code.",
        )
    if not step:
        _name(value["name"])
        _require(
            value.get("order", "ordered") in ("ordered", "multiset"),
            "Observation order must be ordered or multiset.",
        )


CONSTRAINT_NAMES = frozenset(
    name for name in dir(sqlite3) if name.startswith("SQLITE_CONSTRAINT")
)


def validate_suite(suite, limits):
    try:
        encoded = json.dumps(suite, allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        raise RehearsalError("Suite is not finite JSON.") from None
    _require(len(encoded) <= limits.input_bytes, "Suite exceeds the input limit.")
    _keys(suite, ["format", "scenarios"])
    _require(suite["format"] == "schema-rehearsal/v1", "Unsupported suite format.")
    cases = suite["scenarios"]
    _require(
        isinstance(cases, list) and 0 < len(cases) <= 32, "Suite needs 1–32 scenarios."
    )
    names = set()
    for case in cases:
        _keys(case, ["name", "steps", "observations"])
        _name(case["name"])
        _require(case["name"] not in names, "Scenario names must be unique.")
        names.add(case["name"])
        _require(
            isinstance(case["steps"], list) and len(case["steps"]) <= 64,
            "A scenario permits at most 64 steps.",
        )
        _require(
            isinstance(case["observations"], list)
            and 0 < len(case["observations"]) <= 16,
            "A scenario needs 1–16 observations.",
        )
        for step in case["steps"]:
            _query(step, step=True, limits=limits)
        observed = set()
        for obs in case["observations"]:
            _query(obs, step=False, limits=limits)
            _require(
                obs["name"] not in observed,
                "Observation names must be unique within a scenario.",
            )
            observed.add(obs["name"])


def _deadline(deadline):
    if time.monotonic() >= deadline:
        raise RehearsalError("Execution time limit reached.")


def _connect(path, stack, limits):
    db = sqlite3.connect(path, isolation_level=None, timeout=0.1)
    stack.callback(db.close)
    db.execute("PRAGMA temp_store=MEMORY")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA recursive_triggers=ON")
    page_size = db.execute("PRAGMA page_size").fetchone()[0]
    db.execute(f"PRAGMA max_page_count={max(1, limits.database_bytes // page_size)}")
    db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, limits.result_bytes)
    db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, limits.input_bytes)
    db.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 100)
    return db


def _backup(source, dest, limits, deadline):
    def progress(status, remaining, total):
        _deadline(deadline)
        size = source.execute("PRAGMA page_size").fetchone()[0]
        _require(
            total * size <= limits.database_bytes, "Database exceeds the size limit."
        )

    source.backup(dest, pages=128, progress=progress, sleep=0.01)
    page_size = dest.execute("PRAGMA page_size").fetchone()[0]
    dest.execute(f"PRAGMA max_page_count={max(1, limits.database_bytes // page_size)}")


DENIED_ACTIONS = {
    sqlite3.SQLITE_ATTACH,
    sqlite3.SQLITE_DETACH,
    sqlite3.SQLITE_CREATE_VTABLE,
    sqlite3.SQLITE_DROP_VTABLE,
}
READ_PRAGMAS = {
    "table_info",
    "table_xinfo",
    "index_info",
    "index_xinfo",
    "index_list",
    "foreign_key_list",
}
MIGRATION_PRAGMAS = {"foreign_keys", "defer_foreign_keys", "user_version"}
# Functions can allocate output or introduce time/randomness outside reproducible suites.
DENIED_FUNCTIONS = {
    "load_extension",
    "readfile",
    "writefile",
    "random",
    "randomblob",
    "current_timestamp",
    "current_time",
    "current_date",
    "datetime",
    "date",
    "time",
    "julianday",
    "unixepoch",
    "strftime",
}
WRITE_ACTIONS = {
    sqlite3.SQLITE_INSERT,
    sqlite3.SQLITE_UPDATE,
    sqlite3.SQLITE_DELETE,
    sqlite3.SQLITE_CREATE_INDEX,
    sqlite3.SQLITE_CREATE_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_INDEX,
    sqlite3.SQLITE_CREATE_TEMP_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
    sqlite3.SQLITE_CREATE_TEMP_VIEW,
    sqlite3.SQLITE_CREATE_TRIGGER,
    sqlite3.SQLITE_CREATE_VIEW,
    sqlite3.SQLITE_DROP_INDEX,
    sqlite3.SQLITE_DROP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_INDEX,
    sqlite3.SQLITE_DROP_TEMP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_TRIGGER,
    sqlite3.SQLITE_DROP_TEMP_VIEW,
    sqlite3.SQLITE_DROP_TRIGGER,
    sqlite3.SQLITE_DROP_VIEW,
    sqlite3.SQLITE_ALTER_TABLE,
    sqlite3.SQLITE_REINDEX,
    sqlite3.SQLITE_ANALYZE,
}


def _guard(db, deadline, mode):
    def authorize(action, first, second, database, trigger):
        if action in DENIED_ACTIONS or action in {
            sqlite3.SQLITE_CREATE_TEMP_TABLE,
            sqlite3.SQLITE_CREATE_TEMP_INDEX,
            sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
            sqlite3.SQLITE_CREATE_TEMP_VIEW,
        }:
            return sqlite3.SQLITE_DENY
        if (
            action == sqlite3.SQLITE_FUNCTION
            and (second or "").lower() in DENIED_FUNCTIONS
        ):
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_PRAGMA:
            name = (first or "").lower()
            if name in READ_PRAGMAS:
                return sqlite3.SQLITE_OK
            if mode == "migration" and name in MIGRATION_PRAGMAS:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        if mode != "migration" and action in {
            sqlite3.SQLITE_TRANSACTION,
            sqlite3.SQLITE_SAVEPOINT,
        }:
            return sqlite3.SQLITE_DENY
        if mode == "observation" and action in WRITE_ACTIONS:
            return sqlite3.SQLITE_DENY
        if mode == "step" and action in WRITE_ACTIONS - {
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_UPDATE,
            sqlite3.SQLITE_DELETE,
        }:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    db.set_authorizer(authorize)
    db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)


def _unguard(db):
    db.set_authorizer(None)
    db.set_progress_handler(None, 0)


def _statements(script, deadline):
    # Skip quoted/comment semicolons before asking SQLite whether a whole
    # statement (including a trigger body) is complete. Check during scanning,
    # not only after yielding, so an adversarial input cannot starve the timer.
    start, i, state = 0, 0, "normal"
    while i < len(script):
        if i % 1024 == 0:
            _deadline(deadline)
        char = script[i]
        following = script[i + 1] if i + 1 < len(script) else ""
        if state == "line":
            if char in "\r\n":
                state = "normal"
        elif state == "block":
            if char == "*" and following == "/":
                state = "normal"
                i += 1
        elif state != "normal":
            end = "]" if state == "[" else state
            if char == end:
                if following == end and state != "[":
                    i += 1
                else:
                    state = "normal"
        elif char == "-" and following == "-":
            state = "line"
            i += 1
        elif char == "/" and following == "*":
            state = "block"
            i += 1
        elif char in ("'", '"', "`", "["):
            state = char
        elif char == ";":
            _deadline(deadline)
            if sqlite3.complete_statement(script[start : i + 1]):
                yield script[start : i + 1]
                start = i + 1
        i += 1
    _deadline(deadline)
    if script[start:].strip():
        yield script[start:]


def _cell(value):
    if value is None:
        return ("null", "")
    if isinstance(value, bytes):
        return ("blob", value.hex())
    if isinstance(value, str):
        return ("text", value)
    if isinstance(value, int):
        return ("integer", str(value))
    if isinstance(value, float):
        _require(math.isfinite(value), "Observation produced a non-finite real.")
        return ("real", value.hex())
    raise RehearsalError("Unsupported SQLite result value.")


def _rows(cursor, limits, deadline):
    rows, size = [], 0
    while True:
        _deadline(deadline)
        row = cursor.fetchone()
        if row is None:
            break
        typed = tuple(_cell(value) for value in row)
        size += len(json.dumps(typed, ensure_ascii=False).encode())
        _require(
            len(rows) < limits.result_rows and size <= limits.result_bytes,
            "Observation exceeds the result limit.",
        )
        rows.append(typed)
    return rows


def _checks(db, deadline):
    db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    try:
        integrity = db.execute("PRAGMA integrity_check(1)").fetchone() == ("ok",)
        fk_ok = db.execute("PRAGMA foreign_key_check").fetchone() is None
        return {"integrity_ok": integrity, "foreign_keys_ok": fk_ok}
    finally:
        db.set_progress_handler(None, 0)


def _schema(db):
    return {
        (kind, name): hashlib.sha256((sql or "").encode()).hexdigest()
        for kind, name, sql in db.execute(
            "SELECT type,name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
        )
    }


def _scenario(db, case, limits, deadline):
    outcomes, observations = [], []
    for step in case["steps"]:
        _deadline(deadline)
        _guard(db, deadline, "step")
        try:
            # Consume RETURNING/SELECT output as well so steps cannot evade result bounds.
            _rows(db.execute(step["sql"], step.get("parameters", [])), limits, deadline)
            outcome = "ok"
        except sqlite3.IntegrityError as error:
            outcome = error.sqlite_errorname
        finally:
            _unguard(db)
        outcomes.append(outcome)
    for obs in case["observations"]:
        _guard(db, deadline, "observation")
        try:
            cursor = db.execute(obs["sql"], obs.get("parameters", []))
            _require(cursor.description is not None, "Observation must return rows.")
            observations.append(
                (len(cursor.description), _rows(cursor, limits, deadline))
            )
        finally:
            _unguard(db)
    return outcomes, observations


def rehearse(
    database: Path, migration: str, suite: dict, *, limits: Limits | None = None
):
    """Return a value-free report. Only explicitly selected database files are read."""
    limits = limits or Limits()
    report = {
        "format": "schema-rehearsal/report-v1",
        "sqlite_version": sqlite3.sqlite_version,
        "status": "error",
        "exit_code": 2,
        "database_checks": {},
        "schema_changes": [],
        "scenarios": [],
    }
    stage = "input"
    try:
        validate_suite(suite, limits)
        _require(
            isinstance(migration, str)
            and 0 < len(migration.encode()) <= limits.input_bytes,
            "Migration must be nonempty and within the input limit.",
        )
        database = Path(database)
        _require(
            not database.is_symlink() and database.is_file(),
            "Database must be an existing regular file, not a symlink.",
        )
        _require(
            database.stat().st_size <= limits.database_bytes,
            "Database exceeds the size limit.",
        )
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = database.with_name(database.name + suffix)
            _require(
                not sidecar.is_symlink(), "Database sidecar symlinks are unsupported."
            )
            if sidecar.exists():
                _require(
                    sidecar.is_file()
                    and sidecar.stat().st_size <= limits.database_bytes,
                    "Database sidecar exceeds limits or is not a regular file.",
                )
        report["migration_sha256"] = hashlib.sha256(migration.encode()).hexdigest()
        report["suite_sha256"] = hashlib.sha256(
            json.dumps(suite, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        deadline = time.monotonic() + limits.seconds
        with ExitStack() as stack:
            stage = "snapshot"
            source = sqlite3.connect(
                database.resolve().as_uri() + "?mode=ro",
                uri=True,
                isolation_level=None,
                timeout=0.1,
            )
            stack.callback(source.close)
            snapshot = _connect(":memory:", stack, limits)
            _backup(source, snapshot, limits, deadline)
            source.close()
            snapshot.execute("PRAGMA journal_mode=MEMORY")
            _require(
                not snapshot.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type='table' AND upper(sql) LIKE 'CREATE VIRTUAL TABLE%' LIMIT 1"
                ).fetchone(),
                "Virtual-table databases are unsupported.",
            )
            stage = "baseline"
            before_check = _checks(snapshot, deadline)
            report["database_checks"]["before"] = before_check
            if not all(before_check.values()):
                report.update(
                    status="invalid_baseline",
                    exit_code=3,
                    stage=stage,
                    diagnostic="Baseline database checks failed.",
                )
                return report
            report["snapshot_sha256"] = hashlib.sha256(snapshot.serialize()).hexdigest()
            before_schema = _schema(snapshot)
            migrated = _connect(":memory:", stack, limits)
            _backup(snapshot, migrated, limits, deadline)
            stage = "migration"
            _guard(migrated, deadline, "migration")
            try:
                for statement in _statements(migration, deadline):
                    _deadline(deadline)
                    _rows(migrated.execute(statement), limits, deadline)
                _require(
                    not migrated.in_transaction, "Migration left an open transaction."
                )
            finally:
                _unguard(migrated)
            migrated.execute("PRAGMA foreign_keys=ON")
            migrated.execute("PRAGMA recursive_triggers=ON")
            after_check = _checks(migrated, deadline)
            report["database_checks"]["after"] = after_check
            _require(all(after_check.values()), "Migrated database checks failed.")
            after_schema = _schema(migrated)
            for key in sorted(before_schema.keys() | after_schema.keys()):
                if before_schema.get(key) != after_schema.get(key):
                    report["schema_changes"].append(
                        {
                            "type": key[0],
                            "name": key[1],
                            "change": "added"
                            if key not in before_schema
                            else "removed"
                            if key not in after_schema
                            else "changed",
                        }
                    )
            changed = False
            for case in suite["scenarios"]:
                with ExitStack() as scenario_stack:
                    left = _connect(":memory:", scenario_stack, limits)
                    right = _connect(":memory:", scenario_stack, limits)
                    _backup(snapshot, left, limits, deadline)
                    _backup(migrated, right, limits, deadline)
                    stage = "baseline_scenario"
                    baseline_outcomes, baseline_rows = _scenario(
                        left, case, limits, deadline
                    )
                    expected = [
                        step.get("expect_error", "ok") for step in case["steps"]
                    ]
                    if baseline_outcomes != expected:
                        report.update(
                            status="invalid_baseline",
                            exit_code=3,
                            stage=stage,
                            diagnostic="Baseline did not meet declared step outcomes.",
                            scenario=case["name"],
                        )
                        return report
                    stage = "migrated_scenario"
                    migrated_outcomes, migrated_rows = _scenario(
                        right, case, limits, deadline
                    )
                    case_report = {
                        "name": case["name"],
                        "steps": [
                            {"number": i + 1, "before": a, "after": b, "equal": a == b}
                            for i, (a, b) in enumerate(
                                zip(baseline_outcomes, migrated_outcomes)
                            )
                        ],
                        "observations": [],
                    }
                    for obs, (cols_a, a), (cols_b, b) in zip(
                        case["observations"], baseline_rows, migrated_rows
                    ):
                        order = obs.get("order", "ordered")
                        equal = cols_a == cols_b and (
                            a == b if order == "ordered" else Counter(a) == Counter(b)
                        )
                        case_report["observations"].append(
                            {
                                "name": obs["name"],
                                "order": order,
                                "equal": equal,
                                "before_rows": len(a),
                                "after_rows": len(b),
                                "before_columns": cols_a,
                                "after_columns": cols_b,
                            }
                        )
                    case_report["status"] = (
                        "matched"
                        if all(
                            x["equal"]
                            for x in case_report["steps"] + case_report["observations"]
                        )
                        else "changed"
                    )
                    changed |= case_report["status"] == "changed"
                    report["scenarios"].append(case_report)
            report.update(
                status="changed" if changed else "matched",
                exit_code=1 if changed else 0,
            )
    except RehearsalError as error:
        report.update(stage=stage, diagnostic=str(error))
        if stage in ("baseline", "baseline_scenario"):
            report.update(status="invalid_baseline", exit_code=3)
    except (sqlite3.Error, OSError, UnicodeError, OverflowError) as error:
        report.update(
            stage=stage,
            diagnostic="Operation failed; raw error text is omitted to protect application values.",
            error_code=getattr(error, "sqlite_errorname", type(error).__name__),
        )
        if stage in ("baseline", "baseline_scenario"):
            report.update(status="invalid_baseline", exit_code=3)
    return report
