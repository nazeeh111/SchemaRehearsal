"""Small local CLI. Output directories are always exclusive."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .engine import Limits, RehearsalError, rehearse, rehearse_sequence, validate_suite
from .example import create_example
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
        description="Rehearse SQLite migrations on disposable copies with declared application scenarios."
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    example = sub.add_parser(
        "example", help="Create a synthetic fixture in a new directory."
    )
    example.add_argument("directory", type=Path)
    for command, help_text in [
        ("check", "Compare application behaviors; source opens read-only."),
        (
            "sequence",
            "Check each ordered migration checkpoint against one starting snapshot.",
        ),
    ]:
        check = sub.add_parser(command, help=help_text)
        for name in ("database", "suite", "output"):
            check.add_argument("--" + name, required=True, type=Path)
        check.add_argument(
            "--migration",
            required=True,
            type=Path,
            **({"action": "append"} if command == "sequence" else {}),
        )
    args = parser.parse_args(argv)
    try:
        if args.command == "example":
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
        # Reserve output before database execution, including races with another invocation.
        args.output.mkdir(parents=False, exist_ok=False)
        sequence = args.command == "sequence"
        report = (
            rehearse_sequence(args.database, migrations, suite, limits=limits)
            if sequence
            else rehearse(args.database, migrations[0], suite, limits=limits)
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
