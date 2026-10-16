import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from schema_rehearsal.engine import Limits, rehearse, rehearse_sequence


def available():
    try:
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE VIRTUAL TABLE ft USING fts5(body)")
        return True
    except sqlite3.OperationalError:
        return False


UPDATE_TRIGGER = """CREATE TRIGGER articles_au AFTER UPDATE ON articles BEGIN
INSERT INTO search(search,rowid,body) VALUES('delete',old.id,old.body);
INSERT INTO search(rowid,body) VALUES(new.id,new.body); END;"""
SCHEMA = (
    """CREATE TABLE articles(id INTEGER PRIMARY KEY,body TEXT);
CREATE VIRTUAL TABLE search USING fts5(body,content=articles,content_rowid=id);
CREATE TRIGGER articles_ai AFTER INSERT ON articles BEGIN
INSERT INTO search(rowid,body) VALUES(new.id,new.body); END;
CREATE TRIGGER articles_ad AFTER DELETE ON articles BEGIN
INSERT INTO search(search,rowid,body) VALUES('delete',old.id,old.body); END;
"""
    + UPDATE_TRIGGER
)


@unittest.skipUnless(available(), "Built-in SQLite FTS5 unavailable")
class Fts5Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "articles.sqlite"
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript(SCHEMA)
            db.execute("INSERT INTO articles VALUES(1,?)", ("running PRIVATE_SOURCE",))
            db.execute("INSERT INTO articles VALUES(2,?)", ("discarded",))
            db.commit()
        self.suite = {
            "format": "schema-rehearsal/v1",
            "scenarios": [
                {
                    "name": "maintenance",
                    "steps": [
                        {
                            "sql": "INSERT INTO articles VALUES(3,?)",
                            "parameters": ["PRIVATE_INSERT"],
                        },
                        {
                            "sql": "UPDATE articles SET body=? WHERE id=1",
                            "parameters": ["PRIVATE_UPDATE"],
                        },
                        {"sql": "DELETE FROM articles WHERE id=2"},
                    ],
                    "observations": [
                        {
                            "name": "updated",
                            "sql": "SELECT rowid FROM search WHERE search MATCH ?",
                            "parameters": ["PRIVATE_UPDATE"],
                        },
                        {
                            "name": "inserted",
                            "sql": "SELECT rowid FROM search WHERE search MATCH ?",
                            "parameters": ["PRIVATE_INSERT"],
                        },
                        {
                            "name": "deleted",
                            "sql": "SELECT rowid FROM search WHERE search MATCH 'discarded'",
                        },
                    ],
                }
            ],
        }

    def run_case(self, migration="-- unchanged", suite=None, **kwargs):
        return rehearse(
            self.database, migration, suite or self.suite, allow_fts5=True, **kwargs
        )

    def test_trigger_workload_repair_sequence_and_privacy(self):
        before = self.database.read_bytes()
        broken = self.run_case("DROP TRIGGER articles_au;")
        self.assertEqual(broken["status"], "changed", broken)
        self.assertEqual(
            [o["equal"] for o in broken["scenarios"][0]["observations"]],
            [False, True, True],
        )
        self.assertTrue(
            all(c["integrity_ok"] for c in broken["database_checks"].values())
        )
        self.assertEqual(
            self.run_case("DROP TRIGGER articles_au;" + UPDATE_TRIGGER)["status"],
            "matched",
        )
        result = rehearse_sequence(
            self.database,
            ["-- unchanged", "DROP TRIGGER articles_au;", UPDATE_TRIGGER],
            self.suite,
            allow_fts5=True,
        )
        self.assertEqual(
            [c["status"] for c in result["checkpoints"]],
            ["matched", "changed", "matched"],
            result,
        )
        self.assertEqual(
            (result["first_changed"], result["final_status"], result["status"]),
            (2, "matched", "changed"),
        )
        self.assertTrue(result["fts5_enabled"])
        self.assertEqual(before, self.database.read_bytes())
        raw = json.dumps([broken, result])
        for secret in [
            "PRIVATE_SOURCE",
            "PRIVATE_UPDATE",
            "PRIVATE_INSERT",
            "SELECT",
            "INSERT",
            "DROP TRIGGER",
            "parameters",
        ]:
            self.assertNotIn(secret, raw)

    def test_tokenizer_change_with_consistent_rebuilt_index(self):
        suite = {
            "format": "schema-rehearsal/v1",
            "scenarios": [
                {
                    "name": "stemming",
                    "steps": [],
                    "observations": [
                        {
                            "name": "search",
                            "sql": "SELECT rowid FROM search WHERE search MATCH 'run'",
                        }
                    ],
                }
            ],
        }
        migration = """DROP TABLE search;
CREATE VIRTUAL TABLE search USING fts5(body,content=articles,content_rowid=id,tokenize='porter');
INSERT INTO search(search) VALUES('rebuild');"""
        report = self.run_case(migration, suite)
        self.assertEqual(report["status"], "changed", report)
        self.assertEqual(report["scenarios"][0]["observations"][0]["before_rows"], 0)
        self.assertEqual(report["scenarios"][0]["observations"][0]["after_rows"], 1)
        self.assertTrue(
            all(c["integrity_ok"] for c in report["database_checks"].values())
        )

    def test_default_refuses_source_and_virtual_creation(self):
        report = rehearse(self.database, "-- unchanged", self.suite)
        self.assertEqual((report["exit_code"], report["stage"]), (2, "snapshot"))
        self.assertFalse(report["fts5_enabled"])
        ordinary = self.root / "ordinary.sqlite"
        sqlite3.connect(ordinary).close()
        report = rehearse(
            ordinary, "CREATE VIRTUAL TABLE ft USING fts5(a);", self.suite
        )
        self.assertEqual((report["exit_code"], report["stage"]), (2, "migration"))

    def test_sqlite_module_admission_quotes_comments_and_unsupported(self):
        for module in [
            "fts5vocab",
            "fts3",
            "fts4",
            "rtree",
            "not_a_module",
            "fts5_extra",
        ]:
            report = self.run_case(
                f'CREATE VIRTUAL TABLE "using fts5" USING /*fts5*/ "{module}"(a);'
            )
            self.assertEqual(
                (report["exit_code"], report["stage"]),
                (2, "migration"),
                (module, report),
            )
        sql = 'CREATE /*first*/ VIRTUAL TABLE "using fts4" USING /*module*/ [FtS5](a); DROP TABLE "using fts4";'
        self.assertEqual(self.run_case(sql)["status"], "matched")
        for module, args in [("fts4", "a"), ("rtree", "id,minx,maxx")]:
            path = self.root / (module + ".sqlite")
            with closing(sqlite3.connect(path)) as db:
                try:
                    db.execute(
                        f'CREATE VIRTUAL TABLE "fts5 decoy" USING /*fts5*/ {module}({args})'
                    )
                except sqlite3.OperationalError:
                    continue
            self.assertEqual(
                rehearse(path, "-- unchanged", self.suite, allow_fts5=True)[
                    "exit_code"
                ],
                2,
            )

    def test_quoted_source_and_mixed_unsupported_source(self):
        path = self.root / "quoted.sqlite"
        with closing(sqlite3.connect(path)) as db:
            db.execute(
                'CREATE VIRTUAL TABLE "using fts4 ""x" USING /*module*/ [FtS5](body)'
            )
            db.commit()
        suite = {
            "format": "schema-rehearsal/v1",
            "scenarios": [
                {
                    "name": "quoted",
                    "steps": [],
                    "observations": [
                        {
                            "name": "count",
                            "sql": 'SELECT count(*) FROM "using fts4 ""x"',
                        }
                    ],
                }
            ],
        }
        self.assertEqual(
            rehearse(path, "-- unchanged", suite, allow_fts5=True)["status"], "matched"
        )
        for module, args in [
            ("fts5vocab", "search,row"),
            ("rtree", "id,minx,maxx"),
            ("fts3", "body"),
            ("fts4", "body"),
        ]:
            mixed = self.root / ("mixed-" + module + ".sqlite")
            with (
                closing(sqlite3.connect(self.database)) as source,
                closing(sqlite3.connect(mixed)) as db,
            ):
                source.backup(db)
                try:
                    db.execute(
                        f'CREATE VIRTUAL TABLE "decoy USING fts5" USING /*fts5*/ {module}({args})'
                    )
                except sqlite3.OperationalError:
                    continue
            before = mixed.read_bytes()
            report = rehearse(mixed, "-- unchanged", self.suite, allow_fts5=True)
            self.assertEqual(
                (report["exit_code"], report["stage"]), (2, "snapshot"), module
            )
            self.assertEqual(before, mixed.read_bytes())

    def test_opt_in_guards(self):
        for sql in [
            "UPDATE articles SET body='PRIVATE_MUTATION' WHERE id=1 RETURNING id",
            "DELETE FROM search RETURNING rowid",
            "CREATE VIRTUAL TABLE bad USING fts5(a)",
            "DROP TABLE search",
            "BEGIN",
            "SAVEPOINT forbidden",
            "PRAGMA writable_schema=ON",
            "PRAGMA data_version=2",
            "ATTACH ':memory:' AS other",
            "SELECT load_extension('PRIVATE_EXTENSION')",
        ]:
            suite = copy.deepcopy(self.suite)
            suite["scenarios"][0]["steps"] = []
            suite["scenarios"][0]["observations"] = [{"name": "blocked", "sql": sql}]
            report = self.run_case(suite=suite)
            self.assertEqual(report["exit_code"], 3, (sql, report))
        for sql in [
            "CREATE VIRTUAL TABLE bad USING fts5(a)",
            "DROP TABLE search",
            "CREATE TABLE bad(a)",
            "BEGIN",
            "PRAGMA user_version=3",
        ]:
            suite = copy.deepcopy(self.suite)
            suite["scenarios"][0]["steps"] = [{"sql": sql}]
            self.assertEqual(self.run_case(suite=suite)["exit_code"], 3, sql)
        for sql in [
            "CREATE VIRTUAL TABLE temp.bad USING fts5(a)",
            "ATTACH ':memory:' AS other",
            "PRAGMA writable_schema=ON",
            "PRAGMA data_version=2",
            "SELECT load_extension('PRIVATE_EXTENSION')",
        ]:
            self.assertEqual(self.run_case(sql)["exit_code"], 2, sql)
        self.assertEqual(self.run_case(limits=Limits(result_rows=0))["exit_code"], 3)

    def test_cli_opt_in_check_and_sequence(self):
        suite = self.root / "suite.json"
        suite.write_text(json.dumps(self.suite))
        migration = self.root / "unchanged.sql"
        migration.write_text("-- unchanged")
        for command in ["check", "sequence"]:
            output = self.root / command
            run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "schema_rehearsal",
                    command,
                    "--database",
                    str(self.database),
                    "--suite",
                    str(suite),
                    "--migration",
                    str(migration),
                    "--output",
                    str(output),
                    "--allow-fts5",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertTrue(
                json.loads((output / "report.json").read_text())["fts5_enabled"]
            )
