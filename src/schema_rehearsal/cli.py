"""Small local CLI. Output directories are always exclusive."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .engine import Limits, RehearsalError, rehearse, validate_suite
from .example import create_example
from .report import render_html


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
    check = sub.add_parser(
        "check", help="Compare application behaviors; source opens read-only."
    )
    for name in ("database", "migration", "suite", "output"):
        check.add_argument("--" + name, required=True, type=Path)
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
        inputs = [
            args.database.resolve(),
            args.migration.resolve(),
            args.suite.resolve(),
        ]
        if (
            output in inputs
            or any(output in p.parents for p in inputs)
            or len(set(inputs)) != 3
        ):
            raise RehearsalError(
                "Database, migration, suite and output paths must be distinct."
            )
        limits = Limits()
        migration = _read(args.migration, limits.input_bytes)
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
        report = rehearse(args.database, migration, suite, limits=limits)
        for name, text in [
            ("report.json", json.dumps(report, indent=2, ensure_ascii=False) + "\n"),
            ("report.html", render_html(report)),
        ]:
            with (args.output / name).open("x", encoding="utf-8") as file:
                file.write(text)
        print(
            f"{report['status']}: {len(report['scenarios'])} completed scenarios; report.json and report.html written."
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
