"""Exercise the installed CLI's opt-in search workflow with original synthetic data."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=False, exist_ok=False)

    def cli(*args, expected):
        result = subprocess.run(
            [sys.executable, "-m", "schema_rehearsal", *map(str, args)],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != expected:
            raise RuntimeError(
                f"Expected exit {expected}, got {result.returncode}: {result.stderr} {result.stdout}"
            )
        print(result.stdout.strip())

    cli("example", "--fts5", "fixture", expected=0)
    fixture = root / "fixture"
    source = fixture / "articles.sqlite"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    def check(name, migration, suite="suite.json", *, opt_in=True, expected):
        args = [
            "check",
            "--database",
            source,
            "--suite",
            fixture / suite,
            "--migration",
            fixture / migration,
            "--output",
            root / name,
        ]
        if opt_in:
            args.append("--allow-fts5")
        cli(*args, expected=expected)
        return json.loads((root / name / "report.json").read_text())

    default = check("default-refusal", "unchanged.sql", opt_in=False, expected=2)
    broken = check("broken", "broken.sql", expected=1)
    repaired = check("repaired", "repaired.sql", expected=0)
    tokenizer = check(
        "tokenizer", "tokenizer-change.sql", "tokenizer-suite.json", expected=1
    )
    cli(
        "sequence",
        "--allow-fts5",
        "--database",
        source,
        "--suite",
        fixture / "suite.json",
        "--migration",
        fixture / "unchanged.sql",
        "--migration",
        fixture / "broken.sql",
        "--migration",
        fixture / "repair-trigger.sql",
        "--output",
        root / "sequence",
        expected=1,
    )
    sequence = json.loads((root / "sequence/report.json").read_text())
    assert default["stage"] == "snapshot"
    assert [case["status"] for case in broken["scenarios"]] == [
        "changed",
        "matched",
        "matched",
    ]
    witness = broken["scenarios"][0]["observations"][0]
    assert (witness["before_rows"], witness["after_rows"]) == (1, 0)
    assert all(case["status"] == "matched" for case in repaired["scenarios"])
    assert tokenizer["scenarios"][0]["observations"][0]["equal"] is False
    assert [c["status"] for c in sequence["checkpoints"]] == [
        "matched",
        "changed",
        "matched",
    ]
    assert sequence["first_changed"] == 2 and sequence["final_status"] == "matched"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    for report in (broken, repaired, tokenizer, sequence):
        encoded = json.dumps(report)
        for private in (
            "harbor",
            "pearl",
            "quartz",
            "Running rivers",
            str(source),
            "DROP TRIGGER",
        ):
            assert private not in encoded, private
    summary = {
        "fixture": "original synthetic articles, gapped rowids, external-content FTS5",
        "default_exit": 2,
        "broken_exit": 1,
        "repaired_exit": 0,
        "tokenizer_exit": 1,
        "sequence_exit": 1,
        "checkpoint_statuses": [c["status"] for c in sequence["checkpoints"]],
        "first_changed": 2,
        "source_preserved": True,
        "report_values_omitted": True,
    }
    (root / "RESULT.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    print(f"Open {root / 'broken/report.html'}")


if __name__ == "__main__":
    main()
