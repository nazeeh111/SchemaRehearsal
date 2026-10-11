"""Installed, synthetic checkpoint demonstration. Requires a new output path."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from schema_rehearsal.example import TRIGGER, create_example


def main():
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=False, exist_ok=False)
    fixture = root / "fixture"
    create_example(fixture)
    (fixture / "restore.sql").write_text(TRIGGER, encoding="utf-8")
    (fixture / "combined.sql").write_text(
        (fixture / "unchanged.sql").read_text()
        + (fixture / "broken.sql").read_text()
        + TRIGGER,
        encoding="utf-8",
    )
    source_hash = hashlib.sha256((fixture / "orders.sqlite").read_bytes()).hexdigest()
    common = [
        "--database",
        fixture / "orders.sqlite",
        "--suite",
        fixture / "suite.json",
    ]

    def run(command, output, migrations):
        args = [
            sys.executable,
            "-m",
            "schema_rehearsal",
            command,
            *common,
            "--output",
            root / output,
        ]
        for migration in migrations:
            args.extend(["--migration", fixture / migration])
        result = subprocess.run(
            list(map(str, args)), cwd=root, text=True, capture_output=True, check=False
        )
        expected = 0 if command == "check" else 1
        if result.returncode != expected:
            raise RuntimeError(
                f"Unexpected {command} exit {result.returncode}: {result.stderr}"
            )
        print(result.stdout.strip())
        return json.loads((root / output / "report.json").read_text())

    final = run("check", "final-only", ["combined.sql"])
    sequence = run(
        "sequence", "sequence", ["unchanged.sql", "broken.sql", "restore.sql"]
    )
    assert final["status"] == "matched"
    assert [c["status"] for c in sequence["checkpoints"]] == [
        "matched",
        "changed",
        "matched",
    ]
    assert sequence["first_changed"] == 2 and sequence["final_status"] == "matched"
    assert sequence["exit_code"] == 1
    assert (
        hashlib.sha256((fixture / "orders.sqlite").read_bytes()).hexdigest()
        == source_hash
    )
    print(
        json.dumps(
            {
                "final_only": final["status"],
                "sequence_exit": sequence["exit_code"],
                "checkpoint_statuses": [c["status"] for c in sequence["checkpoints"]],
                "first_changed": sequence["first_changed"],
                "source_preserved": True,
            },
            indent=2,
        )
    )
    print(f"Open {root / 'sequence' / 'report.html'}")


if __name__ == "__main__":
    main()
