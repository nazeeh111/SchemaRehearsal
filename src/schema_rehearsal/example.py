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
