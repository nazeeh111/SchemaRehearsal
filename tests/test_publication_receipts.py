import hashlib
import json
import os
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from schema_rehearsal.engine import rehearse_sequence


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "publication_receipts.py"
FIXTURE = runpy.run_path(str(EXAMPLE))


class PublicationReceiptExampleTests(unittest.TestCase):
    def test_cli_distinguishes_receipt_loss_from_repaired_final_state(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "demo"
            env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
            result = subprocess.run(
                [sys.executable, str(EXAMPLE), str(destination)],
                cwd=temp, env=env, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            final = json.loads((destination / "final-only/report.json").read_text())
            sequence = json.loads((destination / "sequence/report.json").read_text())
            self.assertEqual((final["status"], final["exit_code"]), ("matched", 0))
            self.assertEqual(
                (sequence["exit_code"], sequence["first_changed"], sequence["final_status"]),
                (1, 2, "matched"),
            )
            self.assertEqual(
                [c["status"] for c in sequence["checkpoints"]],
                ["matched", "changed", "matched"],
            )
            for index, checkpoint in enumerate(sequence["checkpoints"]):
                report = checkpoint["report"]
                self.assertTrue(all(all(checks.values()) for checks in report["database_checks"].values()))
                invariant, retry, other_account = report["scenarios"]
                self.assertEqual(invariant["observations"][0]["after_rows"], 0)
                self.assertEqual(invariant["observations"][1]["after_rows"], [1, 0, 1][index])
                self.assertEqual(retry["observations"][0]["after_rows"], [0, 1, 0][index])
                self.assertEqual(other_account["status"], "matched")
                self.assertEqual(other_account["observations"][0]["after_rows"], 1)
            source = destination / "fixture/publication.sqlite"
            expected = Path(temp) / "expected"
            FIXTURE["create_fixture"](expected)
            self.assertEqual(
                hashlib.sha256(source.read_bytes()).hexdigest(),
                hashlib.sha256((expected / "publication.sqlite").read_bytes()).hexdigest(),
            )
            # Re-running the example must not replace existing input or reports.
            before = source.read_bytes()
            rerun = subprocess.run(
                [sys.executable, str(EXAMPLE), str(destination)],
                env=env, text=True, capture_output=True,
            )
            self.assertNotEqual(rerun.returncode, 0)
            self.assertEqual(source.read_bytes(), before)

    def test_repair_uses_retained_original_receipt_without_restoring_content(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.executescript(FIXTURE["SCHEMA"])
            for index, sql in enumerate(FIXTURE["MIGRATIONS"].values()):
                db.executescript(sql)
                self.assertEqual(db.execute("SELECT * FROM content").fetchall(), [])
                self.assertEqual(
                    db.execute("SELECT * FROM publication_receipts").fetchall(),
                    [] if index == 1 else [(1, "synthetic-request", 17)],
                )
                self.assertEqual(
                    db.execute("SELECT * FROM retained_receipts").fetchall(),
                    [(1, "synthetic-request", 17)],
                )

    def test_receipt_payload_change_is_detected_even_when_its_count_survives(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / "fixture"
            FIXTURE["create_fixture"](fixture)
            report = rehearse_sequence(
                fixture / "publication.sqlite",
                ["UPDATE publication_receipts SET original_post_id=999;"],
                FIXTURE["SUITE"],
            )
            self.assertEqual(report["exit_code"], 1)
            invariant = report["checkpoints"][0]["report"]["scenarios"][0]
            content, receipt = invariant["observations"]
            self.assertEqual((content["after_rows"], receipt["after_rows"]), (0, 1))
            self.assertEqual(invariant["status"], "changed")

    def test_recreated_original_post_with_changed_request_id_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / "fixture"
            FIXTURE["create_fixture"](fixture)
            report = rehearse_sequence(
                fixture / "publication.sqlite",
                ["INSERT INTO content VALUES(17, 1, 'changed-request', 'synthetic');"],
                FIXTURE["SUITE"],
            )
            self.assertEqual(report["exit_code"], 1)
            invariant = report["checkpoints"][0]["report"]["scenarios"][0]
            content, receipt = invariant["observations"]
            self.assertEqual((content["before_rows"], content["after_rows"]), (0, 1))
            self.assertEqual((receipt["before_rows"], receipt["after_rows"]), (1, 1))
            self.assertEqual(invariant["status"], "changed")


if __name__ == "__main__":
    unittest.main()
