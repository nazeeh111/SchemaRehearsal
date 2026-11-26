"""Small local CLI. Output directories are always exclusive."""

import argparse
import json
import os
import tempfile
import sys
from pathlib import Path

from . import __version__
from .engine import Limits, RehearsalError, rehearse, rehearse_sequence, validate_suite
from .example import create_example, create_fts5_example
from .minimize import minimize
from .report import render_html, render_sequence_html


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise RehearsalError("Duplicate JSON keys are not accepted.")
        value[key] = item
    return value


def _read(path, limit):
    if path.is_symlink() or not path.is_file():
        raise RehearsalError("Inputs must be existing regular files, not symlinks.")
    if path.stat().st_size > limit:
        raise RehearsalError("Input exceeds the size limit.")
    with path.open("rb") as file:
        raw = file.read(limit + 1)
    if len(raw) > limit:
        raise RehearsalError("Input exceeds the size limit.")
    return raw.decode("utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Keepstep: rehearse SQLite migrations on disposable copies with declared application scenarios."
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    example = sub.add_parser(
        "example", help="Create a synthetic fixture in a new directory."
    )
    example.add_argument("directory", type=Path)
    example.add_argument(
        "--fts5",
        action="store_true",
        help="Create a synthetic full-text search fixture.",
    )
    for command, help_text in [
        ("check", "Compare application behaviors; source opens read-only."),
        (
            "sequence",
            "Check each ordered migration checkpoint against one starting snapshot.",
        ),
    ]:
        check = sub.add_parser(command, help=help_text, description=help_text + " Inputs are read from local files; reports omit result cells and SQL. Exit 0 means declared observations match, 1 means a difference, 2 means refusal or execution error, and 3 means an invalid baseline.")
        check.add_argument(
            "--allow-fts5",
            action="store_true",
            help="Allow only built-in FTS5 virtual tables.",
        )
        for name, detail in (("database", "Source SQLite database; opened read-only and copied"),
                             ("suite", "Declared scenario suite JSON"),
                             ("output", "New report directory; existing paths are refused")):
            check.add_argument("--" + name, required=True, type=Path, help=detail)
        check.add_argument(
            "--migration",
            required=True,
            type=Path,
            help="Migration SQL file" + ("; repeat in execution order (up to 8)" if command == "sequence" else ""),
            **({"action": "append"} if command == "sequence" else {}),
        )
    reduction = sub.add_parser("minimize", help="Reduce steps while preserving a selected reported difference.")
    for name in ("database", "migration", "suite", "output"):
        reduction.add_argument("--" + name, required=True, type=Path)
    reduction.add_argument("--scenario", required=True)
    selected = reduction.add_mutually_exclusive_group(required=True)
    selected.add_argument("--observation")
    selected.add_argument("--commit", action="store_true")
    reduction.add_argument("--max-trials", type=int, default=100)
    reduction.add_argument("--seconds", type=float, default=60)
    reduction.add_argument("--allow-fts5", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "example":
            if args.fts5:
                create_fts5_example(args.directory)
                print("Synthetic full-text search example created.")
                return 0
            create_example(args.directory)
            print(
                "Synthetic example created: 20 accounts, 200 orders, three migrations and a scenario suite."
            )
            return 0
        if args.output.exists() or args.output.is_symlink():
            raise RehearsalError(
                "Output already exists. Choose a new directory; existing files are never replaced."
            )
        output = args.output.resolve()
        migration_paths = (
            args.migration if args.command == "sequence" else [args.migration]
        )
        if not 1 <= len(migration_paths) <= 8:
            raise RehearsalError("A sequence needs 1–8 explicitly ordered migrations.")
        inputs = [
            args.database.resolve(),
            args.suite.resolve(),
            *(p.resolve() for p in migration_paths),
        ]
        if (
            output in inputs
            or any(output in p.parents for p in inputs)
            or inputs[0] == inputs[1]
            or any(p in inputs[:2] for p in inputs[2:])
        ):
            raise RehearsalError(
                "Database, suite, migrations and output paths must be distinct."
            )
        limits = Limits()
        migrations = [_read(p, limits.input_bytes) for p in migration_paths]
        if sum(len(sql.encode()) for sql in migrations) > limits.input_bytes:
            raise RehearsalError("Combined migrations exceed the input limit.")
        suite = json.loads(
            _read(args.suite, limits.input_bytes),
            object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(
                RehearsalError("Suite numbers must be finite.")
            ),
        )
        validate_suite(suite, limits)
        sequence = args.command == "sequence"
        if args.command == "minimize":
            reduced, summary = minimize(args.database, migrations[0], suite,
                scenario=args.scenario, observation=args.observation, commit=args.commit,
                max_trials=args.max_trials, seconds=args.seconds, limits=limits,
                allow_fts5=args.allow_fts5)
            fd, temporary = tempfile.mkstemp(prefix=".keepstep-", dir=args.output.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    json.dump(reduced, file, indent=2, ensure_ascii=False)
                    file.write("\n")
                # A hard link publishes the complete file atomically and fails if
                # any destination already exists, including a dangling symlink.
                os.link(temporary, args.output)
            finally:
                os.unlink(temporary)
            print(json.dumps(summary, ensure_ascii=False))
            return 0 if summary["status"] == "complete" else 2
        # Reserve output before database execution, including races with another invocation.
        args.output.mkdir(parents=False, exist_ok=False)
        report = (
            rehearse_sequence(
                args.database,
                migrations,
                suite,
                limits=limits,
                allow_fts5=args.allow_fts5,
            )
            if sequence
            else rehearse(
                args.database,
                migrations[0],
                suite,
                limits=limits,
                allow_fts5=args.allow_fts5,
            )
        )
        for name, text in [
            ("report.json", json.dumps(report, indent=2, ensure_ascii=False) + "\n"),
            (
                "report.html",
                render_sequence_html(report) if sequence else render_html(report),
            ),
        ]:
            with (args.output / name).open("x", encoding="utf-8") as file:
                file.write(text)
        if sequence:
            completed = sum(c["status"] != "not_run" for c in report["checkpoints"])
            first = report["first_changed"]
            detail = (
                f"first changed checkpoint: {first}"
                if first
                else "no observed behavior change"
            )
            print(
                f"{report['status']}: {completed}/{len(migrations)} checkpoints; "
                f"{detail}; final: {report['final_status']}; report.json and report.html written."
            )
        else:
            print(
                f"{report['status']}: {len(report['scenarios'])} completed scenarios; "
                "report.json and report.html written."
            )
        return report["exit_code"]
    except RehearsalError as error:
        print(str(error), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, RecursionError) as error:
        print(
            f"Input or output failed ({type(error).__name__}); raw details omitted.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
