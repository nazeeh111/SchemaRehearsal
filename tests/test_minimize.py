from contextlib import closing
import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from schema_rehearsal.engine import rehearse, RehearsalError, _rehearse_for_minimization
from schema_rehearsal.minimize import minimize


class MinimizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "source.sqlite"
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript("CREATE TABLE items(id INTEGER); CREATE TABLE noise(id INTEGER);")
        self.migration = "CREATE TRIGGER extra AFTER INSERT ON items WHEN NEW.id = 1 BEGIN INSERT INTO items VALUES (99); END;"
        self.suite = {"format": "schema-rehearsal/v1", "scenarios": [{"name": "workflow",
            "steps": [{"sql": f"INSERT INTO noise VALUES ({i})"} for i in range(8)] +
                     [{"sql": "INSERT INTO items VALUES (1)"}] +
                     [{"sql": f"INSERT INTO noise VALUES ({i})"} for i in range(8, 16)],
            "observations": [{"name": "items", "sql": "SELECT id FROM items ORDER BY id"}]}]}

    def test_reduces_and_rechecks_exact_named_report(self):
        original_bytes = self.db.read_bytes()
        before = rehearse(self.db, self.migration, self.suite)
        reduced, summary = minimize(self.db, self.migration, self.suite,
                                    scenario="workflow", observation="items")
        after = rehearse(self.db, self.migration, reduced)
        self.assertEqual(summary["status"], "complete")
        self.assertEqual((summary["original_steps"], summary["remaining_steps"]), (17, 1))
        self.assertEqual(before["scenarios"][0]["observations"], after["scenarios"][0]["observations"])
        self.assertEqual(after["status"], "changed")
        self.assertEqual(self.db.read_bytes(), original_bytes)
        self.assertEqual(len(self.suite["scenarios"][0]["steps"]), 17)

    def test_budget_is_explicit_and_retains_a_valid_witness(self):
        reduced, summary = minimize(self.db, self.migration, self.suite, scenario="workflow",
                                    observation="items", max_trials=3)
        self.assertEqual(summary["status"], "budget_exhausted")
        self.assertEqual(rehearse(self.db, self.migration, reduced)["status"], "changed")

    def test_invalid_baseline_does_not_count_as_preserved(self):
        suite = copy.deepcopy(self.suite)
        suite["scenarios"][0]["steps"].insert(0, {"sql": "INSERT INTO items VALUES (2)",
                                                   "expect_error": "SQLITE_CONSTRAINT"})
        with self.assertRaises(RehearsalError):
            minimize(self.db, self.migration, suite, scenario="workflow", observation="items")

    def test_snapshot_change_stops_reduction(self):
        actual = _rehearse_for_minimization(self.db, self.migration, self.suite,
                                            scenario="workflow", observation="items")
        changed = copy.deepcopy(actual)
        changed[0]["snapshot_sha256"] = "different"
        with patch("schema_rehearsal.minimize._rehearse_for_minimization", side_effect=[actual, changed]):
            with self.assertRaises(RehearsalError):
                minimize(self.db, self.migration, self.suite, scenario="workflow", observation="items")

    def test_commit_witness_keeps_exact_outcomes_and_invalid_deletions(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript("CREATE TABLE parent(id INTEGER PRIMARY KEY);"
                "CREATE TABLE child(id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED);")
        migration = "DROP TABLE child; CREATE TABLE child(id INTEGER);"
        suite = {"format": "schema-rehearsal/v1", "scenarios": [{"name": "deferred",
            "transaction": "commit", "expect_commit_error": "SQLITE_CONSTRAINT_FOREIGNKEY",
            "steps": [{"sql": "INSERT INTO noise VALUES (1)"}, {"sql": "INSERT INTO child VALUES (42)"}],
            "observations": [{"name": "child", "sql": "SELECT id FROM child"}]}]}
        reduced, summary = minimize(self.db, migration, suite, scenario="deferred", commit=True)
        self.assertEqual(summary["status"], "inconclusive")
        self.assertEqual(summary["remaining_steps"], 1)
        self.assertEqual(summary["witness"]["reported_outcome"],
                         {"before": "SQLITE_CONSTRAINT_FOREIGNKEY", "after": "ok", "equal": False})
        self.assertEqual(rehearse(self.db, migration, reduced)["scenarios"][0]["commit"],
                         summary["witness"]["reported_outcome"])

    def test_cli_refuses_existing_and_cleans_up_interruption(self):
        import json
        from schema_rehearsal.cli import main
        root = Path(self.tmp.name)
        sql = root / "migration.sql"
        sql.write_text(self.migration)
        suite = root / "suite.json"
        suite.write_text(json.dumps(self.suite))
        out = root / "output"
        args = ["minimize", "--database", str(self.db), "--migration", str(sql),
                "--suite", str(suite), "--output", str(out), "--scenario", "workflow",
                "--observation", "items"]
        with patch("schema_rehearsal.cli.minimize", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                main(args)
        self.assertFalse(out.exists())
        with patch("schema_rehearsal.cli.os.link", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                main(args)
        self.assertFalse(out.exists())
        self.assertFalse(list(root.glob(".keepstep-*")))
        out.write_text("owned")
        self.assertEqual(main(args), 2)
        self.assertEqual(out.read_text(), "owned")

    def test_same_shape_but_different_values_cannot_replace_witness(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript("CREATE TABLE setting(v INTEGER); INSERT INTO setting VALUES (10);")
        migration = "CREATE TRIGGER adjust AFTER INSERT ON items BEGIN UPDATE items SET id = id + 1; END;"
        suite = {"format": "schema-rehearsal/v1", "scenarios": [{"name": "same",
            "steps": [{"sql": "UPDATE setting SET v = 20"},
                      {"sql": "INSERT INTO items SELECT v FROM setting"}],
            "observations": [{"name": "result", "sql": "SELECT id FROM items"}]}]}
        shortened = copy.deepcopy(suite)
        shortened["scenarios"][0]["steps"].pop(0)
        full_report, full_pair = _rehearse_for_minimization(self.db, migration, suite,
                                        scenario="same", observation="result")
        short_report, short_pair = _rehearse_for_minimization(self.db, migration, shortened,
                                        scenario="same", observation="result")
        self.assertEqual(full_report["scenarios"][0]["observations"],
                         short_report["scenarios"][0]["observations"])
        self.assertNotEqual(full_pair, short_pair)
        reduced, summary = minimize(self.db, migration, suite, scenario="same", observation="result")
        self.assertEqual(summary["remaining_steps"], 2)
        self.assertEqual(reduced, suite)
        import json
        self.assertNotIn('"20"', json.dumps(summary))
        self.assertNotIn('"21"', json.dumps(summary))

    def test_atomic_publication_interrupt_after_link_and_race(self):
        import json
        import os
        from schema_rehearsal.cli import main
        root = Path(self.tmp.name)
        sql = root / "migration.sql"
        sql.write_text(self.migration)
        suite = root / "suite.json"
        suite.write_text(json.dumps(self.suite))
        out = root / "result.json"
        args = ["minimize", "--database", str(self.db), "--migration", str(sql),
                "--suite", str(suite), "--output", str(out), "--scenario", "workflow",
                "--observation", "items"]
        link = os.link
        def interrupt_after(source, destination):
            link(source, destination)
            raise KeyboardInterrupt
        with patch("schema_rehearsal.cli.os.link", side_effect=interrupt_after):
            with self.assertRaises(KeyboardInterrupt):
                main(args)
        self.assertEqual(len(json.loads(out.read_text())["scenarios"][0]["steps"]), 1)
        self.assertFalse(list(root.glob(".keepstep-*")))
        race = root / "race.json"
        args[args.index(str(out))] = str(race)
        def competing_writer(source, destination):
            race.write_text("other owner")
            link(source, destination)
        with patch("schema_rehearsal.cli.os.link", side_effect=competing_writer):
            self.assertEqual(main(args), 2)
        self.assertEqual(race.read_text(), "other owner")
        self.assertFalse(list(root.glob(".keepstep-*")))

    def test_multiset_witness_retains_changed_full_row_set(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript("CREATE TABLE setting(v INTEGER); INSERT INTO setting VALUES (0);")
        migration = "CREATE TRIGGER extra AFTER INSERT ON items WHEN NEW.id=1 BEGIN INSERT INTO items VALUES (3); END;"
        suite = {"format": "schema-rehearsal/v1", "scenarios": [{"name": "multi",
            "steps": [{"sql": "INSERT INTO items VALUES (1)"}, {"sql": "INSERT INTO items VALUES (2)"}],
            "observations": [{"name": "items", "sql": "SELECT id FROM items", "order": "multiset"}]}]}
        reduced, summary = minimize(self.db, migration, suite, scenario="multi", observation="items")
        self.assertEqual(summary["remaining_steps"], 2)
        self.assertEqual(reduced, suite)

    def test_multiset_witness_accepts_reordering_of_identical_rows(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript("CREATE TABLE setting(v INTEGER); INSERT INTO setting VALUES (0);")
        migration = "CREATE TRIGGER extra AFTER INSERT ON items WHEN NEW.id=1 BEGIN INSERT INTO items VALUES (3); END;"
        suite = {"format": "schema-rehearsal/v1", "scenarios": [{"name": "multi",
            "steps": [{"sql": "UPDATE setting SET v=1"}, {"sql": "INSERT INTO items VALUES (1)"}],
            "observations": [{"name": "items", "sql": "SELECT id FROM items ORDER BY CASE WHEN (SELECT v FROM setting)=1 THEN id ELSE -id END", "order": "multiset"}]}]}
        reduced, summary = minimize(self.db, migration, suite, scenario="multi", observation="items")
        self.assertEqual(summary["remaining_steps"], 1)
        self.assertEqual(reduced["scenarios"][0]["steps"][0]["sql"], "INSERT INTO items VALUES (1)")
