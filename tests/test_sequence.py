import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from schema_rehearsal import engine
from schema_rehearsal.engine import Limits, rehearse, rehearse_sequence
from schema_rehearsal.example import TRIGGER, create_example
from schema_rehearsal.report import render_sequence_html


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = self.root / "fixture"
        create_example(self.fixture)
        self.database = self.fixture / "orders.sqlite"
        self.suite = json.loads((self.fixture / "suite.json").read_text())
        self.broken = (self.fixture / "broken.sql").read_text()

    def sequence(self, migrations, **kwargs):
        return rehearse_sequence(self.database, migrations, self.suite, **kwargs)

    def test_recovers_final_state_but_retains_middle_failure(self):
        migrations = ["SELECT 1;", self.broken, TRIGGER]
        final = rehearse(self.database, "\n".join(migrations), self.suite)
        self.assertEqual(final["status"], "matched")
        report = self.sequence(migrations)
        self.assertEqual(
            (report["exit_code"], report["first_changed"], report["final_status"]),
            (1, 2, "matched"),
        )
        self.assertEqual(
            [c["status"] for c in report["checkpoints"]],
            ["matched", "changed", "matched"],
        )
        for checkpoint in report["checkpoints"]:
            self.assertTrue(
                all(
                    all(x.values())
                    for x in checkpoint["report"]["database_checks"].values()
                )
            )
        self.assertEqual(
            {c["report"]["snapshot_sha256"] for c in report["checkpoints"]},
            {report["snapshot_sha256"]},
        )
        self.assertEqual(
            report["checkpoints"][1]["report"]["scenarios"][0]["observations"][1][
                "after_rows"
            ],
            0,
        )
        self.assertEqual(
            report["checkpoints"][2]["report"]["scenarios"][0]["observations"][1][
                "after_rows"
            ],
            17,
        )

    def test_cumulative_data_migrations_and_independent_workloads(self):
        report = self.sequence(
            [
                "UPDATE orders SET total_cents=total_cents+1;",
                "UPDATE orders SET total_cents=total_cents-1;",
            ]
        )
        self.assertEqual(
            [c["status"] for c in report["checkpoints"]], ["changed", "matched"]
        )
        self.assertEqual(report["exit_code"], 1)
        self.assertTrue(
            all(
                c["report"]["scenarios"][2]["status"] == "matched"
                for c in report["checkpoints"]
            )
        )

    def test_error_stops_later_checkpoints(self):
        report = self.sequence(
            ["SELECT 1;", "SELECT PRIVATE_SECRET_FROM_ERROR;", self.broken]
        )
        self.assertEqual(
            [c["status"] for c in report["checkpoints"]],
            ["matched", "error", "not_run"],
        )
        self.assertEqual(report["exit_code"], 2)
        self.assertIsNone(report["first_changed"])
        self.assertNotIn("PRIVATE_SECRET_FROM_ERROR", json.dumps(report))
        self.assertNotIn("report", report["checkpoints"][2])

    def test_open_transaction_cannot_span_files(self):
        report = self.sequence(["BEGIN; UPDATE orders SET total_cents=5;", "COMMIT;"])
        self.assertEqual(
            [c["status"] for c in report["checkpoints"]], ["error", "not_run"]
        )
        self.assertEqual(
            report["checkpoints"][0]["report"]["diagnostic"],
            "Migration left an open transaction.",
        )

    def test_invalid_baseline_stops_and_is_not_reported_matched(self):
        self.suite["scenarios"][0]["steps"][0]["expect_error"] = (
            "SQLITE_CONSTRAINT_CHECK"
        )
        report = self.sequence(["SELECT 1;", "SELECT 2;"])
        self.assertEqual(report["exit_code"], 3)
        self.assertEqual(
            [c["status"] for c in report["checkpoints"]],
            ["invalid_baseline", "not_run"],
        )

    def test_changed_then_execution_error_preserves_first_change(self):
        report = self.sequence([self.broken, "SELECT missing;", TRIGGER])
        self.assertEqual(
            (report["exit_code"], report["first_changed"], report["final_status"]),
            (2, 1, "not_run"),
        )

    def test_bounds_and_whole_sequence_deadline(self):
        for migrations in [[], ["SELECT 1;"] * 9, [""], ["x" * 50, "y" * 51]]:
            with self.subTest(migrations=migrations):
                report = self.sequence(migrations, limits=Limits(input_bytes=100))
                self.assertEqual(report["exit_code"], 2)
                self.assertEqual(report["checkpoints"], [])
        report = self.sequence(["SELECT 1;"] * 8, limits=Limits(seconds=-1))
        self.assertEqual(report["exit_code"], 2)
        self.assertEqual(report["checkpoints"][-1]["status"], "not_run")

    def test_wal_snapshot_is_frozen_even_if_original_writer_changes(self):
        writer = sqlite3.connect(self.database)
        self.addCleanup(writer.close)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO accounts VALUES(21, 'committed WAL row')")
        writer.commit()
        original = engine._scenario
        seen = []

        def observe(db, case, limits, deadline, allow_fts5=False):
            result = original(db, case, limits, deadline, allow_fts5)
            seen.append(db.execute("SELECT count(*) FROM accounts").fetchone()[0])
            if len(seen) == 1:
                writer.execute("INSERT INTO accounts VALUES(22, 'later source row')")
                writer.commit()
            return result

        with patch.object(engine, "_scenario", side_effect=observe):
            report = self.sequence(["SELECT 1;", "SELECT 2;"])
        self.assertEqual(report["exit_code"], 0)
        self.assertEqual(set(seen), {21})
        self.assertEqual(
            writer.execute("SELECT count(*) FROM accounts").fetchone()[0], 22
        )

    def test_source_preserved_and_report_excludes_private_values(self):
        before = {p.name: p.read_bytes() for p in self.fixture.iterdir()}
        self.suite["scenarios"][0]["observations"].append(
            {"name": "private probe", "sql": "SELECT 'UNIQUE_PRIVATE_CELL'"}
        )
        report = self.sequence([self.broken, TRIGGER])
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.fixture.iterdir()}
        )
        html = render_sequence_html(report)
        for text in (json.dumps(report), html):
            self.assertNotIn("UNIQUE_PRIVATE_CELL", text)
            self.assertNotIn(str(self.database), text)
            self.assertNotIn(self.broken, text)
        self.assertIn("Final checkpoint: <strong>matched</strong>", html)

    def test_html_escapes_names_and_reports_stopped_checkpoint(self):
        self.suite["scenarios"][0]["name"] = "<script>PRIVATE_MARKER</script>"
        html = render_sequence_html(
            self.sequence([self.broken, "SELECT missing;", TRIGGER])
        )
        self.assertIn("&lt;script&gt;PRIVATE_MARKER&lt;/script&gt;", html)
        self.assertNotIn("<script>PRIVATE_MARKER</script>", html)
        self.assertIn("not_run", html)
        self.assertIn("raw error text is omitted", html)

    def test_sequence_identity_binds_order_and_repeated_migrations(self):
        a, b = "SELECT 1;", "SELECT 2;"
        forward, reverse = self.sequence([a, b]), self.sequence([b, a])
        self.assertNotEqual(forward["sequence_sha256"], reverse["sequence_sha256"])
        self.assertEqual(self.sequence([a, a])["exit_code"], 0)
        self.assertEqual(
            forward["checkpoints"][0]["migration_sha256"],
            hashlib.sha256(a.encode()).hexdigest(),
        )

    def test_single_checkpoint_preserves_single_report(self):
        migration = (self.fixture / "repaired.sql").read_text()
        self.assertEqual(
            self.sequence([migration])["checkpoints"][0]["report"],
            rehearse(self.database, migration, self.suite),
        )

    def test_partial_change_is_retained_when_later_scenario_errors(self):
        with sqlite3.connect(self.database) as db:
            db.executescript(
                "CREATE TABLE t(x); INSERT INTO t VALUES(1); CREATE TABLE u(y); INSERT INTO u VALUES(10);"
            )
        self.suite = {
            "format": "schema-rehearsal/v1",
            "scenarios": [
                {
                    "name": "first",
                    "steps": [],
                    "observations": [{"name": "value", "sql": "SELECT x FROM t"}],
                },
                {
                    "name": "second",
                    "steps": [],
                    "observations": [{"name": "value", "sql": "SELECT y FROM u"}],
                },
            ],
        }
        report = self.sequence(["UPDATE t SET x=2; DROP TABLE u;", "SELECT 1;"])
        self.assertEqual((report["exit_code"], report["first_changed"]), (2, 1))
        self.assertEqual(
            report["checkpoints"][0]["report"]["scenarios"][0]["status"], "changed"
        )
        self.assertEqual(report["final_status"], "not_run")

    def test_invalid_baseline_preserves_single_migration_identity(self):
        with sqlite3.connect(self.database) as db:
            db.executescript(
                "CREATE TABLE invalid(parent REFERENCES accounts(id)); INSERT INTO invalid VALUES(999);"
            )
        migration = "SELECT 1;"
        report = rehearse(self.database, migration, self.suite)
        self.assertEqual(report["exit_code"], 3)
        self.assertEqual(
            report["migration_sha256"], hashlib.sha256(migration.encode()).hexdigest()
        )

    def test_sequence_html_retains_commit_failure_context(self):
        self.suite = {
            "format": "schema-rehearsal/v1",
            "scenarios": [
                {
                    "name": "<failed transaction>",
                    "steps": [],
                    "transaction": "commit",
                    "expect_commit_error": "SQLITE_CONSTRAINT_FOREIGNKEY",
                    "observations": [{"name": "value", "sql": "SELECT 1"}],
                }
            ],
        }
        report = self.sequence(["SELECT 1;", "SELECT 2;"])
        html = render_sequence_html(report)
        self.assertEqual(report["exit_code"], 3)
        self.assertIn("Scenario: &lt;failed transaction&gt;", html)
        self.assertIn(
            "Baseline commit: ok · expected SQLITE_CONSTRAINT_FOREIGNKEY", html
        )
