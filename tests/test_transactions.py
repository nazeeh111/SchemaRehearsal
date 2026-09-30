import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
import time

from schema_rehearsal.engine import Limits, RehearsalError, rehearse, validate_suite, _scenario
from schema_rehearsal.report import render_html


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "synthetic.sqlite"
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript("""
                CREATE TABLE parents(id INTEGER PRIMARY KEY);
                CREATE TABLE children(id INTEGER PRIMARY KEY, parent_id INTEGER
                  REFERENCES parents(id) DEFERRABLE INITIALLY DEFERRED);
            """)

    def case(self, steps=None, **fields):
        return {
            "name": "Related records", "transaction": "commit",
            "steps": steps if steps is not None else [
                {"sql": "INSERT INTO children VALUES(?,?)", "parameters": [1, 9]},
                {"sql": "INSERT INTO parents VALUES(?)", "parameters": [9]},
            ],
            "observations": [{"name": "Linked children", "sql": "SELECT id FROM children ORDER BY id"}],
            **fields,
        }

    def run_case(self, case, migration="PRAGMA user_version=1;"):
        return rehearse(self.database, migration, {"format": "schema-rehearsal/v1", "scenarios": [case]})

    def test_deferred_child_before_parent_commits_and_default_stays_autocommit(self):
        before = self.database.read_bytes()
        report = self.run_case(self.case())
        self.assertEqual(report["status"], "matched")
        case = report["scenarios"][0]
        self.assertEqual(case["commit"], {"before": "ok", "after": "ok", "equal": True})
        self.assertEqual(case["observations"][0]["before_rows"], 1)
        autocommit = self.case()
        del autocommit["transaction"]
        self.assertEqual(self.run_case(autocommit)["status"], "invalid_baseline")
        self.assertEqual(self.database.read_bytes(), before)

    def test_immediate_constraint_migration_changes_step_outcomes(self):
        report = self.run_case(self.case(), """
            DROP TABLE children;
            CREATE TABLE children(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parents(id));
        """)
        self.assertEqual(report["status"], "changed")
        self.assertEqual(report["scenarios"][0]["steps"][0]["after"], "SQLITE_CONSTRAINT_FOREIGNKEY")
        self.assertEqual(report["scenarios"][0]["observations"][0]["after_rows"], 0)

    def test_expected_commit_constraint_rolls_back_before_observation(self):
        case = self.case(steps=[{"sql": "INSERT INTO children VALUES(1,9)"}], expect_commit_error="SQLITE_CONSTRAINT_FOREIGNKEY")
        report = self.run_case(case)
        self.assertEqual(report["status"], "matched")
        result = report["scenarios"][0]
        self.assertEqual(result["commit"]["before"], "SQLITE_CONSTRAINT_FOREIGNKEY")
        self.assertEqual(result["observations"][0]["before_rows"], 0)
        self.assertEqual(result["observations"][0]["after_rows"], 0)
        del case["expect_commit_error"]
        self.assertEqual(self.run_case(case)["status"], "invalid_baseline")

    def test_migration_changing_commit_outcome_is_changed(self):
        case = self.case(steps=[{"sql": "INSERT INTO children VALUES(1,9)"}], expect_commit_error="SQLITE_CONSTRAINT_FOREIGNKEY")
        report = self.run_case(case, "DROP TABLE children; CREATE TABLE children(id INTEGER PRIMARY KEY, parent_id INTEGER);")
        self.assertEqual(report["status"], "changed")
        self.assertEqual(report["scenarios"][0]["commit"], {"before": "SQLITE_CONSTRAINT_FOREIGNKEY", "after": "ok", "equal": False})
        self.assertEqual(report["scenarios"][0]["observations"][0]["after_rows"], 1)

    def test_migrated_failed_commit_rolls_back_all_steps(self):
        report = self.run_case(self.case(), """
            CREATE TRIGGER ignore_parent BEFORE INSERT ON parents
            BEGIN SELECT RAISE(IGNORE); END;
        """)
        self.assertEqual(report["status"], "changed")
        result = report["scenarios"][0]
        self.assertTrue(all(s["equal"] for s in result["steps"]))
        self.assertEqual(result["commit"], {
            "before": "ok", "after": "SQLITE_CONSTRAINT_FOREIGNKEY", "equal": False,
        })
        self.assertEqual(result["observations"][0]["after_rows"], 0)

    def test_trigger_implicit_rollback_skips_later_steps_and_observes_settled_state(self):
        case = self.case(steps=[
            {"sql": "INSERT INTO parents VALUES(2)"},
            {"sql": "INSERT INTO children VALUES(1,2)"},
            {"sql": "INSERT INTO parents VALUES(3)"},
        ], observations=[{"name": "Parents", "sql": "SELECT id FROM parents ORDER BY id"}])
        report = self.run_case(case, "CREATE TRIGGER stop_insert BEFORE INSERT ON children BEGIN SELECT RAISE(ROLLBACK,'PRIVATE_ROLLBACK_MESSAGE'); END;")
        self.assertEqual(report["status"], "changed")
        result = report["scenarios"][0]
        self.assertEqual([s["after"] for s in result["steps"]], ["ok", "SQLITE_CONSTRAINT_TRIGGER", "not_run"])
        self.assertEqual(result["commit"]["after"], "not_attempted")
        self.assertEqual(result["observations"][0]["after_rows"], 0)
        self.assertNotIn("PRIVATE_ROLLBACK_MESSAGE", json.dumps(report) + render_html(report))

    def test_constraint_abort_continues_but_constraint_rollback_does_not(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript("CREATE TABLE numbers(n INTEGER UNIQUE ON CONFLICT ABORT); INSERT INTO numbers VALUES(99);")
        case = self.case(steps=[
            {"sql": "INSERT INTO numbers VALUES(55)"},
            {"sql": "INSERT INTO numbers VALUES(99)", "expect_error": "SQLITE_CONSTRAINT_UNIQUE"},
            {"sql": "INSERT INTO numbers VALUES(77)"},
        ], observations=[{"name": "Numbers", "sql": "SELECT n FROM numbers ORDER BY n"}])
        report = self.run_case(case, "DROP TABLE numbers; CREATE TABLE numbers(n INTEGER UNIQUE ON CONFLICT ROLLBACK); INSERT INTO numbers VALUES(99);")
        self.assertEqual(report["status"], "changed")
        result = report["scenarios"][0]
        self.assertEqual([s["before"] for s in result["steps"]], ["ok", "SQLITE_CONSTRAINT_UNIQUE", "ok"])
        self.assertEqual([s["after"] for s in result["steps"]], ["ok", "SQLITE_CONSTRAINT_UNIQUE", "not_run"])
        self.assertEqual(result["commit"], {"before": "ok", "after": "not_attempted", "equal": False})
        self.assertEqual(result["observations"][0]["before_rows"], 3)
        self.assertEqual(result["observations"][0]["after_rows"], 1)

    def test_insert_or_rollback_baseline_records_skipped_steps(self):
        case = self.case(steps=[
            {"sql": "INSERT INTO parents VALUES(1)"},
            {"sql": "INSERT OR ROLLBACK INTO parents VALUES(1)", "expect_error": "SQLITE_CONSTRAINT_PRIMARYKEY"},
            {"sql": "INSERT INTO parents VALUES(2)"},
        ])
        report = self.run_case(case)
        self.assertEqual(report["status"], "invalid_baseline")
        self.assertEqual(report["commit"]["before"], "not_attempted")
        self.assertEqual([s["actual"] for s in report["steps"]], ["ok", "SQLITE_CONSTRAINT_PRIMARYKEY", "not_run"])

    def test_interrupted_transaction_is_settled_and_handler_cleared(self):
        with closing(sqlite3.connect(":memory:", isolation_level=None)) as db:
            db.execute("CREATE TABLE parents(id INTEGER PRIMARY KEY)")
            case = self.case(steps=[{"sql": "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<10000000) INSERT INTO parents SELECT x FROM n"}])
            with self.assertRaises((sqlite3.OperationalError, RehearsalError)):
                _scenario(db, case, Limits(), time.monotonic() + .005)
            self.assertFalse(db.in_transaction)
            self.assertEqual(db.execute("SELECT count(*) FROM parents").fetchone(), (0,))

    def test_transaction_fields_and_manual_control_are_strict(self):
        for fields in [{"transaction": True}, {"transaction": "rollback"},
                       {"transaction": "commit", "expect_commit_error": "SQLITE_AUTH"},
                       {"expect_commit_error": "SQLITE_CONSTRAINT_FOREIGNKEY"}]:
            case = self.case()
            del case["transaction"]
            case.update(fields)
            with self.subTest(fields=fields), self.assertRaises(RehearsalError):
                validate_suite({"format": "schema-rehearsal/v1", "scenarios": [case]}, Limits())
        for sql in ["BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT nested"]:
            with self.subTest(sql=sql):
                report = self.run_case(self.case(steps=[{"sql": sql}]))
                self.assertEqual(report["status"], "invalid_baseline")
                self.assertEqual(report["error_code"], "SQLITE_AUTH")

    def test_post_commit_observations_keep_guards_limits_and_privacy(self):
        for sql in ["DELETE FROM parents", "SELECT random()"]:
            report = self.run_case(self.case(observations=[{"name": "Guard", "sql": sql}]))
            self.assertEqual(report["error_code"], "SQLITE_AUTH" if sql.startswith("DELETE") else "SQLITE_ERROR")
        case = self.case(observations=[{"name": "Bound", "sql": "SELECT 1 UNION ALL SELECT 2"}])
        report = rehearse(self.database, "SELECT 1;", {"format": "schema-rehearsal/v1", "scenarios": [case]}, limits=Limits(result_rows=1))
        self.assertEqual(report["status"], "invalid_baseline")
        case = self.case(name="<script>case</script>", observations=[{"name": "Private result", "sql": "SELECT 'PRIVATE_CELL'"}])
        report = self.run_case(case)
        html = render_html(report)
        self.assertIn("Commit", html)
        self.assertIn("&lt;script&gt;case&lt;/script&gt;", html)
        self.assertNotIn("<script>case</script>", html)
        self.assertNotIn("PRIVATE_CELL", json.dumps(report) + html)
