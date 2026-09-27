import json
import pathlib
import tempfile
import unittest

from schema_rehearsal.engine import rehearse
from schema_rehearsal.example import create_example


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        create_example(self.root / "fixture")
        self.fixture = self.root / "fixture"

    def run_case(self, migration="repaired.sql", suite=None, **kw):
        return rehearse(
            self.fixture / "orders.sqlite",
            (self.fixture / migration).read_text(),
            suite or json.loads((self.fixture / "suite.json").read_text()),
            **kw,
        )

    def test_detects_lost_trigger_despite_integrity_checks(self):
        report = self.run_case("broken.sql")
        self.assertEqual(report["status"], "changed")
        self.assertEqual(report["exit_code"], 1)
        self.assertTrue(
            all(c["integrity_ok"] for c in report["database_checks"].values())
        )
        changed = [x for x in report["scenarios"][0]["observations"] if not x["equal"]]
        self.assertEqual([x["name"] for x in changed], ["audit coverage"])

    def test_repaired_and_unchanged_pass(self):
        for migration in ["repaired.sql", "unchanged.sql"]:
            with self.subTest(migration=migration):
                self.assertEqual(self.run_case(migration)["exit_code"], 0)

    def test_source_files_unchanged(self):
        before = {p.name: p.read_bytes() for p in self.fixture.iterdir()}
        self.run_case("broken.sql")
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.fixture.iterdir()}
        )

    def test_report_contains_no_sql_parameters_or_cells(self):
        suite = {
            "format": "schema-rehearsal/v1",
            "scenarios": [
                {
                    "name": "probe",
                    "steps": [],
                    "observations": [
                        {"name": "cell", "sql": "SELECT 'PRIVATE_UNIQUE_CELL'"}
                    ],
                }
            ],
        }
        raw = json.dumps(self.run_case(suite=suite))
        self.assertNotIn("PRIVATE_UNIQUE_CELL", raw)
        self.assertNotIn("SELECT", raw)


if __name__ == "__main__":
    unittest.main()
