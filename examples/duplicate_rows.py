"""Run the walkthrough with an installed SchemaRehearsal, using synthetic data."""

import json
from pathlib import Path
import sqlite3
import subprocess
import sys


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python duplicate_rows.py NEW_DIRECTORY")
    root = Path(sys.argv[1]).resolve()
    root.mkdir(exist_ok=False)
    database = root / "receipt.sqlite"
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE line_items(id INTEGER PRIMARY KEY, sku TEXT NOT NULL,
                                    quantity INTEGER NOT NULL CHECK(quantity>0));
            INSERT INTO line_items VALUES(1,'A',1),(2,'A',1),(3,'B',1);
        """)
    db.close()
    suite = {
        "format": "schema-rehearsal/v1",
        "scenarios": [{
            "name": "Receipt contents",
            "steps": [],
            "observations": [
                {"name": "Line count", "sql": "SELECT count(*) FROM line_items"},
                {"name": "Items including duplicates",
                 "sql": "SELECT sku,quantity FROM line_items ORDER BY id",
                 "order": "multiset"},
            ],
        }],
    }
    (root / "suite.json").write_text(json.dumps(suite, indent=2) + "\n")
    migrations = {
        "reordered": """
            BEGIN;
            CREATE TABLE replacement(id INTEGER PRIMARY KEY, sku TEXT NOT NULL,
                                     quantity INTEGER NOT NULL CHECK(quantity>0));
            INSERT INTO replacement(sku,quantity)
                SELECT sku,quantity FROM line_items ORDER BY sku DESC,id;
            DROP TABLE line_items;
            ALTER TABLE replacement RENAME TO line_items;
            COMMIT;
        """,
        "duplicate_changed": """
            UPDATE line_items SET sku='B' WHERE id=2;
        """,
    }
    results = {}
    for name, sql in migrations.items():
        migration = root / (name + ".sql")
        migration.write_text(sql)
        output = root / name
        run = subprocess.run([
            sys.executable, "-m", "schema_rehearsal", "check",
            "--database", str(database), "--migration", str(migration),
            "--suite", str(root / "suite.json"), "--output", str(output),
        ], cwd=root, check=False)
        expected = 0 if name == "reordered" else 1
        if run.returncode != expected:
            raise SystemExit(f"{name}: expected exit {expected}, got {run.returncode}")
        report = json.loads((output / "report.json").read_text())
        observations = report["scenarios"][0]["observations"]
        if not observations[0]["equal"] or observations[1]["equal"] != (expected == 0):
            raise SystemExit(f"{name}: unexpected observation result")
        if not all(all(checks.values()) for checks in report["database_checks"].values()):
            raise SystemExit(f"{name}: unexpected database check failure")
        results[name] = {"exit": run.returncode, "status": report["status"]}
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
