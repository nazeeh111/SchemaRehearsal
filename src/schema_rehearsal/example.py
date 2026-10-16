"""Create an original, synthetic application fixture, exclusively."""

import json
import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE accounts(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE orders(id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id), total_cents INTEGER NOT NULL CHECK(total_cents>=0), status TEXT NOT NULL CHECK(status IN ('open','paid')));
CREATE TABLE audit(order_id INTEGER NOT NULL, old_status TEXT, new_status TEXT NOT NULL);
CREATE TRIGGER order_status AFTER UPDATE OF status ON orders BEGIN INSERT INTO audit VALUES(NEW.id, OLD.status, NEW.status); END;
"""
MIGRATION = """-- Rebuild orders to add an optional note. The broken version forgets its trigger.
BEGIN;
CREATE TABLE orders_new(id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id), total_cents INTEGER NOT NULL CHECK(total_cents>=0), status TEXT NOT NULL CHECK(status IN ('open','paid')), note TEXT);
INSERT INTO orders_new(id,account_id,total_cents,status) SELECT id,account_id,total_cents,status FROM orders;
DROP TABLE orders;
ALTER TABLE orders_new RENAME TO orders;
COMMIT;
"""
TRIGGER = """CREATE TRIGGER order_status AFTER UPDATE OF status ON orders
BEGIN
  INSERT INTO audit VALUES(NEW.id, OLD.status, NEW.status);
END;
"""
SUITE = {
    "format": "schema-rehearsal/v1",
    "scenarios": [
        {
            "name": "Pay seventeen orders",
            "steps": [
                {
                    "sql": "UPDATE orders SET status='paid' WHERE id BETWEEN ? AND ?",
                    "parameters": [1, 17],
                }
            ],
            "observations": [
                {
                    "name": "paid count",
                    "sql": "SELECT count(*) FROM orders WHERE status='paid'",
                },
                {
                    "name": "audit coverage",
                    "sql": "SELECT order_id,old_status,new_status FROM audit ORDER BY order_id",
                },
            ],
        },
        {
            "name": "Reject negative amount",
            "steps": [
                {
                    "sql": "UPDATE orders SET total_cents=? WHERE id=?",
                    "parameters": [-1, 1],
                    "expect_error": "SQLITE_CONSTRAINT_CHECK",
                }
            ],
            "observations": [
                {
                    "name": "amount preserved",
                    "sql": "SELECT total_cents FROM orders WHERE id=1",
                }
            ],
        },
        {
            "name": "Independent starting state",
            "steps": [],
            "observations": [
                {
                    "name": "all still open",
                    "sql": "SELECT count(*) FROM orders WHERE status='open'",
                },
                {"name": "no inherited audit", "sql": "SELECT count(*) FROM audit"},
            ],
        },
    ],
}


def create_example(directory: Path):
    directory = Path(directory)
    directory.mkdir(parents=False, exist_ok=False)
    db = sqlite3.connect(directory / "orders.sqlite")
    try:
        db.executescript(SCHEMA)
        db.executemany(
            "INSERT INTO accounts VALUES(?,?)",
            [(i, f"Synthetic account {i}") for i in range(1, 21)],
        )
        db.executemany(
            "INSERT INTO orders VALUES(?,?,?,?)",
            [(i, 1 + i % 20, 100 + i, "open") for i in range(1, 201)],
        )
        db.commit()
    finally:
        db.close()
    for name, text in {
        "broken.sql": MIGRATION,
        "repaired.sql": MIGRATION + TRIGGER,
        "unchanged.sql": "-- A no-op baseline comparison.\nSELECT 1;\n",
        "suite.json": json.dumps(SUITE, indent=2) + "\n",
    }.items():
        with (directory / name).open("x", encoding="utf-8") as file:
            file.write(text)


FTS5_SCHEMA = """
CREATE TABLE articles(id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL);
CREATE VIRTUAL TABLE search USING fts5(title, body, content='articles', content_rowid='id', tokenize='porter unicode61');
CREATE TRIGGER articles_ai AFTER INSERT ON articles BEGIN
  INSERT INTO search(rowid,title,body) VALUES(new.id,new.title,new.body);
END;
CREATE TRIGGER articles_ad AFTER DELETE ON articles BEGIN
  INSERT INTO search(search,rowid,title,body) VALUES('delete',old.id,old.title,old.body);
END;
"""
FTS5_UPDATE_TRIGGER = """CREATE TRIGGER articles_au AFTER UPDATE ON articles BEGIN
  INSERT INTO search(search,rowid,title,body) VALUES('delete',old.id,old.title,old.body);
  INSERT INTO search(rowid,title,body) VALUES(new.id,new.title,new.body);
END;
"""
FTS5_SUITE = {
    "format": "schema-rehearsal/v1",
    "scenarios": [
        {
            "name": "Search an updated article",
            "steps": [
                {
                    "sql": "UPDATE articles SET body=? WHERE id=?",
                    "parameters": ["harbor lantern guides the ferry", 1],
                }
            ],
            "observations": [
                {
                    "name": "Updated article appears in search",
                    "sql": "SELECT rowid FROM search WHERE search MATCH ? ORDER BY rowid",
                    "parameters": ["harbor"],
                }
            ],
        },
        {
            "name": "Search an inserted article",
            "steps": [
                {
                    "sql": "INSERT INTO articles VALUES(?,?,?)",
                    "parameters": [
                        29,
                        "Silver orchard",
                        "pearl blossoms in the morning",
                    ],
                }
            ],
            "observations": [
                {
                    "name": "Inserted article appears in search",
                    "sql": "SELECT rowid FROM search WHERE search MATCH ? ORDER BY rowid",
                    "parameters": ["pearl"],
                }
            ],
        },
        {
            "name": "Remove a deleted article from search",
            "steps": [{"sql": "DELETE FROM articles WHERE id=?", "parameters": [17]}],
            "observations": [
                {
                    "name": "Deleted article has no search hit",
                    "sql": "SELECT rowid FROM search WHERE search MATCH ? ORDER BY rowid",
                    "parameters": ["quartz"],
                }
            ],
        },
    ],
}
FTS5_TOKENIZER_SUITE = {
    "format": "schema-rehearsal/v1",
    "scenarios": [
        {
            "name": "Keep the application search vocabulary",
            "steps": [],
            "observations": [
                {
                    "name": "Stemmed query finds its article",
                    "sql": "SELECT rowid FROM search WHERE search MATCH ? ORDER BY rowid",
                    "parameters": ["run"],
                }
            ],
        }
    ],
}


def create_fts5_example(directory: Path):
    """Create original synthetic search data; requires SQLite's built-in FTS5."""
    from .engine import RehearsalError

    probe = sqlite3.connect(":memory:")
    try:
        probe.execute("CREATE VIRTUAL TABLE search USING fts5(body)")
    except sqlite3.Error:
        raise RehearsalError(
            "This SQLite build cannot create the built-in FTS5 example."
        ) from None
    finally:
        probe.close()
    directory = Path(directory)
    directory.mkdir(parents=False, exist_ok=False)
    db = sqlite3.connect(directory / "articles.sqlite")
    try:
        db.executescript(FTS5_SCHEMA + FTS5_UPDATE_TRIGGER)
        db.executemany(
            "INSERT INTO articles VALUES(?,?,?)",
            [
                (1, "Running rivers", "a river runs past the old mill"),
                (8, "Cedar forest", "a green canopy shelters the trail"),
                (17, "Night train", "quartz gravel beside the railway"),
            ],
        )
        db.commit()
    finally:
        db.close()
    for name, text in {
        "broken.sql": "-- Content survives; the next update stops reaching search.\nDROP TRIGGER articles_au;\n",
        "repaired.sql": "DROP TRIGGER articles_au;\n" + FTS5_UPDATE_TRIGGER,
        "repair-trigger.sql": FTS5_UPDATE_TRIGGER,
        "unchanged.sql": "-- A no-op checkpoint.\nSELECT 1;\n",
        "tokenizer-change.sql": """-- Rebuild a consistent index with different search semantics.
DROP TABLE search;
CREATE VIRTUAL TABLE search USING fts5(title,body,content='articles',content_rowid='id',tokenize='unicode61');
INSERT INTO search(search) VALUES('rebuild');
""",
        "suite.json": json.dumps(FTS5_SUITE, indent=2) + "\n",
        "tokenizer-suite.json": json.dumps(FTS5_TOKENIZER_SUITE, indent=2) + "\n",
    }.items():
        with (directory / name).open("x", encoding="utf-8") as file:
            file.write(text)
