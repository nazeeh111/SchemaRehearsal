import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "schema_rehearsal", *map(str, args)],
            capture_output=True,
            check=False,
            text=True,
        )

    def check(self, fixture, out, migration="repaired.sql"):
        return self.cli(
            "check",
            "--database",
            fixture / "orders.sqlite",
            "--migration",
            fixture / migration,
            "--suite",
            fixture / "suite.json",
            "--output",
            out,
        )

    def test_example_and_reports(self):
        fixture = self.root / "fixture"
        self.assertEqual(self.cli("example", fixture).returncode, 0)
        out = self.root / "report"
        result = self.check(fixture, out, "broken.sql")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(
            json.loads((out / "report.json").read_text())["status"], "changed"
        )
        self.assertIn("Pay seventeen orders", (out / "report.html").read_text())
        self.assertNotIn("Synthetic account", (out / "report.html").read_text())

    def test_existing_output_and_example_are_preserved(self):
        fixture = self.root / "fixture"
        self.cli("example", fixture)
        self.assertEqual(self.cli("example", fixture).returncode, 2)
        out = self.root / "report"
        out.mkdir()
        (out / "keep").write_text("keep")
        self.assertEqual(self.check(fixture, out).returncode, 2)
        self.assertEqual(list(out.iterdir()), [out / "keep"])

    def test_duplicate_json_key_rejected(self):
        fixture = self.root / "fixture"
        self.cli("example", fixture)
        (fixture / "suite.json").write_text(
            '{"format":"schema-rehearsal/v1","scenarios":[],"scenarios":[]}'
        )
        self.assertEqual(self.check(fixture, self.root / "report").returncode, 2)

    def test_html_escapes_metadata(self):
        fixture = self.root / "fixture"
        self.cli("example", fixture)
        suite = json.loads((fixture / "suite.json").read_text())
        suite["scenarios"][0]["name"] = "<script>UNTRUSTED</script>"
        (fixture / "suite.json").write_text(json.dumps(suite))
        out = self.root / "report"
        self.assertEqual(self.check(fixture, out).returncode, 0)
        html = (out / "report.html").read_text()
        self.assertNotIn("<script>UNTRUSTED</script>", html)
        self.assertIn("&lt;script&gt;UNTRUSTED&lt;/script&gt;", html)


class SequenceCliTests(unittest.TestCase):
    setUp = CliTests.setUp
    cli = CliTests.cli

    def sequence(self, fixture, output, *migrations):
        args = [
            "sequence",
            "--database",
            fixture / "orders.sqlite",
            "--suite",
            fixture / "suite.json",
            "--output",
            output,
        ]
        for migration in migrations:
            args.extend(["--migration", fixture / migration])
        return self.cli(*args)

    def test_ordered_sequence_and_existing_output_preserved(self):
        from schema_rehearsal.example import TRIGGER

        fixture = self.root / "fixture"
        self.assertEqual(self.cli("example", fixture).returncode, 0)
        (fixture / "restore.sql").write_text(TRIGGER)
        output = self.root / "sequence"
        run = self.sequence(
            fixture, output, "unchanged.sql", "broken.sql", "restore.sql"
        )
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertIn("first changed checkpoint: 2; final: matched", run.stdout)
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(
            [c["status"] for c in report["checkpoints"]],
            ["matched", "changed", "matched"],
        )
        prior = {p.name: p.read_bytes() for p in output.iterdir()}
        self.assertEqual(self.sequence(fixture, output, "unchanged.sql").returncode, 2)
        self.assertEqual(prior, {p.name: p.read_bytes() for p in output.iterdir()})

    def test_excess_count_and_combined_bytes_rejected_before_output(self):
        fixture = self.root / "fixture"
        self.cli("example", fixture)
        output = self.root / "output"
        self.assertEqual(
            self.sequence(fixture, output, *(["unchanged.sql"] * 9)).returncode, 2
        )
        self.assertFalse(output.exists())
        (fixture / "a.sql").write_text("--" + "a" * 600000)
        (fixture / "b.sql").write_text("--" + "b" * 600000)
        self.assertEqual(self.sequence(fixture, output, "a.sql", "b.sql").returncode, 2)
        self.assertFalse(output.exists())

    def test_same_file_repetition_and_symlink_rejection(self):
        fixture = self.root / "fixture"
        self.cli("example", fixture)
        self.assertEqual(
            self.sequence(
                fixture, self.root / "repeated", "unchanged.sql", "unchanged.sql"
            ).returncode,
            0,
        )
        (fixture / "link.sql").symlink_to("unchanged.sql")
        self.assertEqual(
            self.sequence(fixture, self.root / "linked", "link.sql").returncode, 2
        )
        self.assertFalse((self.root / "linked").exists())


if __name__ == "__main__":
    unittest.main()
