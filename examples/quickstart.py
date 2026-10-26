"""Run a synthetic migration example from source, without installation."""

import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys

# Deliberately use this checkout's engine, including in an uninstalled source archive.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from schema_rehearsal.cli import main as cli_main


def run_demo(directory, *, fts5=False):
    root = Path(directory)
    root.mkdir(parents=False, exist_ok=False)
    fixture = root / "fixture"
    with contextlib.redirect_stdout(io.StringIO()):
        code = cli_main(["example", *(["--fts5"] if fts5 else []), str(fixture)])
    if code != 0:
        raise RuntimeError("The synthetic fixture could not be created.")
    database = fixture / ("articles.sqlite" if fts5 else "orders.sqlite")
    label = "search hits" if fts5 else "audit rows"
    expected_rows = 1 if fts5 else 17
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    results = []
    for name, expected in [("broken", 1), ("repaired", 0), ("unchanged", 0)]:
        output = root / name
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli_main([
                "check", "--database", str(database),
                "--migration", str(fixture / f"{name}.sql"),
                "--suite", str(fixture / "suite.json"), "--output", str(output),
                *(["--allow-fts5"] if fts5 else []),
            ])
        if code != expected:
            raise RuntimeError(f"{name}: expected exit {expected}, received {code}.")
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        if report["exit_code"] != expected:
            raise RuntimeError(f"{name}: report and command exit disagree.")
        checks = report["database_checks"]
        if not checks or not all(
            check["integrity_ok"] and check["foreign_keys_ok"]
            for check in checks.values()
        ):
            raise RuntimeError(f"{name}: a database check did not pass.")
        observation = report["scenarios"][0]["observations"][0 if fts5 else 1]
        after_rows = 0 if name == "broken" else expected_rows
        if (observation["before_rows"], observation["after_rows"], observation["equal"]) != (
            expected_rows, after_rows, name != "broken"
        ):
            raise RuntimeError(f"{name}: unexpected {label} observation.")
        results.append({
            "migration": name, "exit_code": code, "status": report["status"],
            "observation": label,
            "rows_before": observation["before_rows"],
            "rows_after": observation["after_rows"],
            "report": f"{name}/report.html",
        })
        print(f"{name:9} exit {code}  {label} {observation['before_rows']} -> {observation['after_rows']}")
    after = hashlib.sha256(database.read_bytes()).hexdigest()
    if before != after:
        raise RuntimeError("The generated source database bytes changed.")
    summary = {
        "fixture": "synthetic FTS5 articles" if fts5 else "synthetic orders", "source_sha256_before": before,
        "source_sha256_after": after, "results": results,
    }
    with (root / "summary.json").open("x", encoding="utf-8") as file:
        file.write(json.dumps(summary, indent=2) + "\n")
    print("All three runs passed integrity and foreign-key checks.")
    if fts5:
        print("These general checks do not establish FTS5 index/content consistency.")
    print("Generated source database bytes unchanged.")
    print(f"Open {(root / 'broken/report.html').resolve()}")
    print("Demo verified. Exit 0 means the expected 1/0/0 results were reproduced.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="New output directory with an existing parent")
    parser.add_argument("--fts5", action="store_true", help="Use the search example; requires built-in SQLite FTS5")
    args = parser.parse_args()
    try:
        run_demo(args.directory, fts5=args.fts5)
    except (OSError, RuntimeError, ValueError, KeyError, IndexError) as error:
        print(f"Demo could not finish: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
