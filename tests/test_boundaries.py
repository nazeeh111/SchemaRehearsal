import copy
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from schema_rehearsal.engine import Limits, rehearse
from schema_rehearsal.example import create_example


def suite_for(sql="SELECT count(*) FROM orders", steps=None, order="ordered"):
    return {
        "format": "schema-rehearsal/v1",
        "scenarios": [
            {
                "name": "probe",
                "steps": steps or [],
                "observations": [{"name": "observation", "sql": sql, "order": order}],
            }
        ],
    }


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        create_example(self.root / "example")
        self.db = self.root / "example/orders.sqlite"

    def run_case(self, migration="SELECT 1;", suite=None, limits=None):
        return rehearse(self.db, migration, suite or suite_for(), limits=limits)

    def test_committed_wal_is_in_snapshot_and_source_data_unchanged(self):
        writer = sqlite3.connect(self.db)
        self.addCleanup(writer.close)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO orders VALUES(201,1,500,'open')")
        writer.commit()
        wal = self.db.with_name(self.db.name + "-wal")
        self.assertGreater(wal.stat().st_size, 0)
        main_bytes = self.db.read_bytes()
        wal_bytes = wal.read_bytes()
        steps = [
            {
                "sql": "INSERT INTO orders SELECT 202,1,500,'open' WHERE (SELECT count(*) FROM orders)=201"
            }
        ]
        result = self.run_case(
            suite=suite_for("SELECT id FROM orders ORDER BY id", steps)
        )
        self.assertEqual(result["exit_code"], 0, result)
        self.assertEqual(result["scenarios"][0]["observations"][0]["before_rows"], 202)
        self.assertEqual(main_bytes, self.db.read_bytes())
        self.assertEqual(wal_bytes, wal.read_bytes())
        self.assertEqual(
            writer.execute("SELECT count(*) FROM orders").fetchone()[0], 201
        )

    def test_scenarios_start_independently(self):
        case = suite_for(
            "SELECT id FROM orders ORDER BY id",
            [{"sql": "DELETE FROM orders WHERE id=1"}],
        )
        second = copy.deepcopy(case["scenarios"][0])
        second["name"] = "second"
        second["steps"] = []
        case["scenarios"].append(second)
        result = self.run_case(suite=case)
        self.assertEqual(
            [c["observations"][0]["before_rows"] for c in result["scenarios"]],
            [199, 200],
        )

    def test_forbidden_migration_operations_have_no_external_effects(self):
        external = self.root / "external.sqlite"
        for sql in [
            f"ATTACH DATABASE '{external}' AS external;",
            "DETACH DATABASE main;",
            f"VACUUM INTO '{external}';",
            "SELECT load_extension('private_extension');",
            "PRAGMA writable_schema=ON;",
            "PRAGMA journal_mode=OFF;",
            "PRAGMA ignore_check_constraints=ON;",
            "PRAGMA temp_store_directory='/tmp';",
            "CREATE VIRTUAL TABLE vt USING fts5(body);",
        ]:
            with self.subTest(sql=sql):
                result = self.run_case(sql)
                self.assertEqual(result["exit_code"], 2, result)
                self.assertFalse(external.exists())

    def test_observation_cannot_write_or_change_pragmas(self):
        for sql in [
            "DELETE FROM orders RETURNING id",
            "PRAGMA foreign_keys=OFF",
            "BEGIN",
        ]:
            with self.subTest(sql=sql):
                self.assertEqual(self.run_case(suite=suite_for(sql))["exit_code"], 3)
        self.assertEqual(self.run_case()["exit_code"], 0)

    def test_step_cannot_change_schema_or_start_transaction(self):
        for sql in ["DROP TABLE orders", "BEGIN", "PRAGMA user_version=3"]:
            with self.subTest(sql=sql):
                self.assertEqual(
                    self.run_case(suite=suite_for(steps=[{"sql": sql}]))["exit_code"], 3
                )

    def test_expected_constraint_is_exact_and_can_change(self):
        case = suite_for(
            steps=[
                {
                    "sql": "UPDATE orders SET total_cents=-1 WHERE id=1",
                    "expect_error": "SQLITE_CONSTRAINT_CHECK",
                }
            ]
        )
        self.assertEqual(self.run_case(suite=case)["exit_code"], 0)
        wrong = copy.deepcopy(case)
        wrong["scenarios"][0]["steps"][0]["expect_error"] = "SQLITE_CONSTRAINT_UNIQUE"
        self.assertEqual(self.run_case(suite=wrong)["exit_code"], 3)
        migration = """BEGIN; CREATE TABLE n(id INTEGER PRIMARY KEY,account_id INTEGER,total_cents INTEGER,status TEXT); INSERT INTO n SELECT * FROM orders; DROP TABLE orders; ALTER TABLE n RENAME TO orders; COMMIT;"""
        self.assertEqual(self.run_case(migration, case)["exit_code"], 1)

    def test_invalid_baseline_foreign_keys(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE orders SET account_id=999 WHERE id=1")
        result = self.run_case()
        self.assertEqual(result["exit_code"], 3)
        self.assertFalse(result["database_checks"]["before"]["foreign_keys_ok"])

    def test_observations_preserve_type_duplicate_multiplicity_and_order(self):
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TABLE values_table(value)")
            db.executemany("INSERT INTO values_table VALUES(?)", [(1,), (1,), (2,)])
        # Same printable cell, distinct SQLite type.
        self.assertEqual(
            self.run_case(
                "UPDATE values_table SET value=CAST(value AS TEXT);",
                suite_for("SELECT value FROM values_table"),
            )["exit_code"],
            1,
        )
        # Reordering preserves a multiset, not an ordered sequence.
        migration = (
            "DELETE FROM values_table; INSERT INTO values_table VALUES(2),(1),(1);"
        )
        self.assertEqual(
            self.run_case(
                migration, suite_for("SELECT value FROM values_table ORDER BY rowid")
            )["exit_code"],
            1,
        )
        self.assertEqual(
            self.run_case(
                migration, suite_for("SELECT value FROM values_table", order="multiset")
            )["exit_code"],
            0,
        )
        self.assertEqual(
            self.run_case(
                "DELETE FROM values_table WHERE rowid=1;",
                suite_for("SELECT value FROM values_table", order="multiset"),
            )["exit_code"],
            1,
        )

    def test_multistatement_trigger_and_quoted_semicolons(self):
        sql = "CREATE TABLE events(value); CREATE TRIGGER event_trigger AFTER INSERT ON events BEGIN INSERT INTO audit VALUES(1,'semi;colon','x'); INSERT INTO audit VALUES(2,'y','z'); END; INSERT INTO events VALUES('a;b');"
        result = self.run_case(sql, suite_for("SELECT count(*) FROM audit"))
        self.assertEqual(result["exit_code"], 1, result)

    def test_open_migration_transaction_rejected(self):
        self.assertEqual(self.run_case("BEGIN; SELECT 1;")["exit_code"], 2)

    def test_runtime_and_result_bounds(self):
        loop = "WITH RECURSIVE r(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM r) SELECT sum(x) FROM r"
        self.assertEqual(
            self.run_case(loop + ";", limits=Limits(seconds=0.02))["exit_code"], 2
        )
        self.assertEqual(
            self.run_case(
                suite=suite_for("SELECT id FROM orders"), limits=Limits(result_rows=2)
            )["exit_code"],
            3,
        )
        self.assertEqual(
            self.run_case(
                suite=suite_for("SELECT id FROM orders"),
                limits=Limits(result_bytes=1000),
            )["exit_code"],
            3,
        )

    def test_temporary_tables_cannot_bypass_page_budget(self):
        result = self.run_case(
            "CREATE TEMP TABLE giant(x); INSERT INTO giant VALUES(zeroblob(500000));",
            limits=Limits(database_bytes=32768),
        )
        self.assertEqual(result["exit_code"], 2, result)
        self.assertEqual(result["error_code"], "SQLITE_AUTH")

    def test_quoted_semicolon_scanner_is_bounded(self):
        start = time.monotonic()
        result = self.run_case(
            "SELECT '" + ";" * 200000 + "';", limits=Limits(seconds=0.02)
        )
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertIn(result["exit_code"], (0, 2), result)

    def test_splitter_handles_comments_and_escaped_quotes(self):
        result = self.run_case(
            "-- ; ignore\nSELECT 'a'';b'; /* ; ignore */ SELECT 1;", suite_for()
        )
        self.assertEqual(result["exit_code"], 0, result)

    def test_database_size_bound(self):
        self.assertEqual(
            self.run_case(limits=Limits(database_bytes=10))["exit_code"], 2
        )
        self.assertEqual(
            self.run_case(
                "CREATE TABLE huge(v); INSERT INTO huge VALUES(zeroblob(1000000));",
                limits=Limits(database_bytes=32768),
            )["exit_code"],
            2,
        )

    def test_invalid_suite_shapes_and_numbers(self):
        variants = [
            {},
            {"format": "schema-rehearsal/v1", "scenarios": []},
            {"format": "wrong", "scenarios": []},
        ]
        for value in [True, 2**64, float("nan"), {}, []]:
            case = suite_for(steps=[{"sql": "SELECT ?", "parameters": [value]}])
            variants.append(case)
        for expected in ({}, [], 3):
            variants.append(
                suite_for(steps=[{"sql": "SELECT 1", "expect_error": expected}])
            )
        duplicate = suite_for()
        duplicate["scenarios"] *= 2
        variants.append(duplicate)
        case = suite_for()
        case["scenarios"][0]["extra"] = 1
        variants.append(case)
        for case in variants:
            with self.subTest(case=case):
                result = rehearse(self.db, "SELECT 1;", case)
                self.assertEqual(result["exit_code"], 2, result)
                self.assertEqual(result["stage"], "input")

    def test_raw_sqlite_errors_never_leak_values(self):
        value = "PRIVATE_ERROR_VALUE"
        result = self.run_case(f"SELECT {value};")
        self.assertEqual(result["exit_code"], 2)
        self.assertNotIn(value, json.dumps(result))

    def test_nondeterministic_functions_rejected(self):
        self.assertEqual(
            self.run_case(suite=suite_for("SELECT random()"))["exit_code"], 3
        )


if __name__ == "__main__":
    unittest.main()
