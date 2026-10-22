"""Synthetic deleted-post receipt example; no application integration is claimed."""

import hashlib
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

# Inspired by TheodorNEngoy's suggested preservation contract:
# https://github.com/simonw/datasette/discussions/2997#discussioncomment-18870847
SCHEMA = """
CREATE TABLE content(
    post_id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    request_id TEXT NOT NULL,
    body TEXT NOT NULL,
    UNIQUE(account_id, request_id)
);
CREATE TABLE publication_receipts(
    account_id INTEGER NOT NULL,
    request_id TEXT NOT NULL,
    original_post_id INTEGER NOT NULL,
    PRIMARY KEY(account_id, request_id)
);
INSERT INTO content VALUES(17, 1, 'synthetic-request', 'synthetic removed post');
INSERT INTO publication_receipts VALUES(1, 'synthetic-request', 17);
DELETE FROM content WHERE post_id=17;
"""
MIGRATIONS = {
    "001-retain.sql": """-- Synthetic retained recovery source, independent of content.
CREATE TABLE retained_receipts AS SELECT * FROM publication_receipts;
""",
    "002-prune.sql": """-- Deliberately wrong: deletion does not make a receipt obsolete.
DELETE FROM publication_receipts
WHERE NOT EXISTS (
    SELECT 1 FROM content
    WHERE content.account_id=publication_receipts.account_id
      AND content.request_id=publication_receipts.request_id
);
""",
    "003-restore.sql": """-- Restore original keys and payload from the retained source.
INSERT INTO publication_receipts(account_id, request_id, original_post_id)
SELECT account_id, request_id, original_post_id FROM retained_receipts
WHERE NOT EXISTS (
    SELECT 1 FROM publication_receipts
    WHERE publication_receipts.account_id=retained_receipts.account_id
      AND publication_receipts.request_id=retained_receipts.request_id
);
""",
}
RETRY = """INSERT INTO content(post_id, account_id, request_id, body)
SELECT ?, ?, ?, 'synthetic retry' WHERE NOT EXISTS (
    SELECT 1 FROM publication_receipts WHERE account_id=? AND request_id=?
)"""
RECEIPT = {
    "name": "Original receipt survives",
    "sql": "SELECT account_id,request_id,original_post_id FROM publication_receipts WHERE account_id=1 AND request_id='synthetic-request'",
}
CONTENT = {
    "name": "Deleted content stays absent",
    "sql": "SELECT post_id FROM content WHERE post_id=17 OR (account_id=1 AND request_id='synthetic-request')",
}
SUITE = {
    "format": "schema-rehearsal/v1",
    "scenarios": [
        {
            "name": "Deleted post invariant",
            "steps": [],
            "observations": [CONTENT, RECEIPT],
        },
        {
            "name": "Same account delayed retry",
            "steps": [{"sql": RETRY, "parameters": [101, 1, "synthetic-request", 1, "synthetic-request"]}],
            "observations": [CONTENT, RECEIPT],
        },
        {
            "name": "Another account may reuse the request ID",
            "steps": [{"sql": RETRY, "parameters": [202, 2, "synthetic-request", 2, "synthetic-request"]}],
            "observations": [{
                "name": "Independent account publishes",
                "sql": "SELECT post_id,account_id,request_id FROM content WHERE account_id=2 ORDER BY post_id",
            }],
        },
    ],
}


def create_fixture(directory):
    directory = Path(directory)
    directory.mkdir(parents=False, exist_ok=False)
    with closing(sqlite3.connect(directory / "publication.sqlite")) as db:
        db.executescript(SCHEMA)
    files = {
        **MIGRATIONS,
        "combined.sql": "\n".join(MIGRATIONS.values()),
        "suite.json": json.dumps(SUITE, indent=2) + "\n",
    }
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")


def main():
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=False, exist_ok=False)
    fixture = root / "fixture"
    create_fixture(fixture)
    source = fixture / "publication.sqlite"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    def run(command, output, migrations, expected_exit):
        args = [sys.executable, "-m", "schema_rehearsal", command,
                "--database", source, "--suite", fixture / "suite.json",
                "--output", root / output]
        for migration in migrations:
            args.extend(["--migration", fixture / migration])
        result = subprocess.run(list(map(str, args)), text=True, capture_output=True)
        if result.returncode != expected_exit:
            raise RuntimeError(f"Unexpected {command} exit {result.returncode}: {result.stderr}")
        print(result.stdout.strip())
        return json.loads((root / output / "report.json").read_text())

    final = run("check", "final-only", ["combined.sql"], 0)
    sequence = run("sequence", "sequence", list(MIGRATIONS), 1)
    assert final["status"] == "matched"
    assert [c["status"] for c in sequence["checkpoints"]] == ["matched", "changed", "matched"]
    assert sequence["first_changed"] == 2 and sequence["final_status"] == "matched"
    cases = [c["report"]["scenarios"] for c in sequence["checkpoints"]]
    observed = {
        "deleted_content_rows": [c[0]["observations"][0]["after_rows"] for c in cases],
        "original_receipt_rows": [c[0]["observations"][1]["after_rows"] for c in cases],
        "same_account_retry_content_rows": [c[1]["observations"][0]["after_rows"] for c in cases],
        "other_account_content_rows": [c[2]["observations"][0]["after_rows"] for c in cases],
    }
    assert list(observed.values()) == [[0, 0, 0], [1, 0, 1], [0, 1, 0], [1, 1, 1]]
    assert all(
        all(checks.values())
        for checkpoint in sequence["checkpoints"]
        for checks in checkpoint["report"]["database_checks"].values()
    )
    print(json.dumps(observed, indent=2))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    print("Final-only matched; sequence retained checkpoint 2's failure; source preserved.")
    print(f"Open {root / 'sequence' / 'report.html'}")


if __name__ == "__main__":
    main()
