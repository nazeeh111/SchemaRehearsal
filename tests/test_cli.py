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


if __name__ == "__main__":
    unittest.main()
