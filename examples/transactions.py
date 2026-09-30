"""Rehearse deferred foreign keys with an installed wheel and synthetic data."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python transactions.py NEW_DIRECTORY")
    root = Path(sys.argv[1]).resolve()
    root.mkdir(exist_ok=False)
    database = root / "relations.sqlite"
    with closing(sqlite3.connect(database)) as db:
        db.executescript("""
            CREATE TABLE parents(id INTEGER PRIMARY KEY);
            CREATE TABLE children(id INTEGER PRIMARY KEY, parent_id INTEGER
                REFERENCES parents(id) DEFERRABLE INITIALLY DEFERRED);
        """)
    original = database.read_bytes()
    linked = {
        "name": "Child before parent",
        "transaction": "commit",
        "steps": [
            {"sql": "INSERT INTO children VALUES(?,?)", "parameters": [1, 9]},
            {"sql": "INSERT INTO parents VALUES(?)", "parameters": [9]},
        ],
        "observations": [{
            "name": "Linked children", "sql": "SELECT id FROM children ORDER BY id",
        }],
    }
    rejected = {
        **linked,
        "name": "Missing parent rejected at commit",
        "steps": linked["steps"][:1],
        "expect_commit_error": "SQLITE_CONSTRAINT_FOREIGNKEY",
    }
    autocommit = {key: value for key, value in linked.items() if key != "transaction"}
    unexpected = {key: value for key, value in rejected.items() if key != "expect_commit_error"}
    unchanged = "PRAGMA user_version=1;"
    immediate = """
        DROP TABLE children;
        CREATE TABLE children(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parents(id));
    """
    runs = [
        ("deferred", [linked, rejected], unchanged, 0),
        ("immediate", [linked, rejected], immediate, 1),
        ("autocommit", [autocommit], unchanged, 3),
        ("unexpected_commit", [unexpected], unchanged, 3),
    ]
    results = {}
    for name, scenarios, sql, expected_exit in runs:
        suite = root / (name + ".json")
        suite.write_text(json.dumps({"format": "schema-rehearsal/v1", "scenarios": scenarios}, indent=2) + "\n")
        migration = root / (name + ".sql")
        migration.write_text(sql)
        result = subprocess.run([
            sys.executable, "-m", "schema_rehearsal", "check",
            "--database", str(database), "--migration", str(migration),
            "--suite", str(suite), "--output", str(root / name),
        ], cwd=root, check=False)
        if result.returncode != expected_exit:
            raise SystemExit(f"{name}: expected exit {expected_exit}, got {result.returncode}")
        report = json.loads((root / name / "report.json").read_text())
        if report["exit_code"] != expected_exit or not (root / name / "report.html").is_file():
            raise SystemExit(f"{name}: incomplete report")
        if name == "deferred":
            valid, failed = report["scenarios"]
            if valid["commit"]["before"] != "ok" or valid["observations"][0]["before_rows"] != 1:
                raise SystemExit("Deferred relationship did not commit")
            if failed["commit"]["before"] != "SQLITE_CONSTRAINT_FOREIGNKEY" or failed["observations"][0]["before_rows"] != 0:
                raise SystemExit("Failed commit did not roll back before observation")
        if name == "immediate" and report["scenarios"][0]["steps"][0]["after"] != "SQLITE_CONSTRAINT_FOREIGNKEY":
            raise SystemExit("Immediate constraint difference was not recorded")
        if name == "unexpected_commit" and report["commit"]["before"] != "SQLITE_CONSTRAINT_FOREIGNKEY":
            raise SystemExit("Unexpected baseline commit was not recorded")
        results[name] = {"exit": result.returncode, "status": report["status"]}
    if database.read_bytes() != original:
        raise SystemExit("Synthetic source database changed")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
