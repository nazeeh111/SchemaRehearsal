"""Run directly with the interpreter containing the installed wheel, without PYTHONPATH."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(root, *args):
    return subprocess.run(
        [sys.executable, "-m", "schema_rehearsal", *map(str, args)],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )


with tempfile.TemporaryDirectory(prefix="schema-rehearsal-installed-") as name:
    root = Path(name)
    result = run(root, "example", "fixture")
    assert result.returncode == 0, result.stderr
    for migration, expected in [("broken", 1), ("repaired", 0), ("unchanged", 0)]:
        result = run(
            root,
            "check",
            "--database",
            "fixture/orders.sqlite",
            "--migration",
            f"fixture/{migration}.sql",
            "--suite",
            "fixture/suite.json",
            "--output",
            migration,
        )
        assert result.returncode == expected, (
            migration,
            result.returncode,
            result.stderr,
        )
        report = json.loads((root / migration / "report.json").read_text())
        assert report["exit_code"] == expected
        assert (root / migration / "report.html").is_file()
    identity = subprocess.run(
        [
            sys.executable,
            "-c",
            "import schema_rehearsal; print(schema_rehearsal.__file__)",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert "site-packages" in identity, identity
    print(
        json.dumps(
            {
                "installed_module": identity,
                "broken_exit": 1,
                "repaired_exit": 0,
                "unchanged_exit": 0,
                "outside_source": True,
            }
        )
    )
