"""File-backed migration and multi-feature user-data lifecycle tests."""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from wealth.core import execute, initialize, SCHEMA_VERSION


class LifecycleTests(unittest.TestCase):
    def test_unversioned_database_migrates_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "prior.sqlite3")
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE accounts (user_id TEXT,id TEXT,name TEXT,kind TEXT,balance_cents INTEGER,apr_bps INTEGER,as_of TEXT,source TEXT,PRIMARY KEY(user_id,id))")
                db.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)", ("old", "checking", "Checking", "cash", 12345, 0, "2025-01-01", "manual"))
                db.execute("CREATE TABLE tasks (user_id TEXT,task_id TEXT,response TEXT,PRIMARY KEY(user_id,task_id))")
                db.commit()
                initialize(db)
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
                self.assertEqual(db.execute("SELECT balance_cents FROM accounts WHERE user_id='old'").fetchone()[0], 12345)
                self.assertIn("request_hash", {row[1] for row in db.execute("PRAGMA table_info(tasks)")})
                initialize(db)
                self.assertEqual(db.execute("SELECT count(*) FROM accounts").fetchone()[0], 1)
                db.execute(f"PRAGMA user_version={SCHEMA_VERSION+1}")
                with self.assertRaisesRegex(ValueError, "newer"):
                    initialize(db)

    def test_failed_migration_rolls_back_ddl(self):
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE TABLE transactions (user_id TEXT, fingerprint TEXT)")
            db.commit()
            with self.assertRaises(sqlite3.OperationalError):
                initialize(db)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='accounts'").fetchone())

    def test_export_and_erase_only_target_one_user(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "wealth.sqlite3")
            with sqlite3.connect(path) as db:
                initialize(db)
                serial = 0
                def task(user, action, data=None, assumptions=None):
                    nonlocal serial
                    serial += 1
                    payload = {"task_id": str(serial), "user_id": user, "action": action, "data": data or {}}
                    if assumptions is not None:
                        payload["assumptions"] = assumptions
                    return execute(db, payload)["result"]
                today = datetime.now(timezone.utc).date().isoformat()
                for user in ("alice", "bob"):
                    task(user, "upsert_profile", {"currency": "USD", "timezone": "UTC", "tax_jurisdiction": "US"})
                    task(user, "upsert_account", {"id": "bank", "name": "Bank", "kind": "cash", "balance_cents": 300000, "as_of": today})
                task("alice", "upsert_cashflow", {"id": "pay", "label": "Pay", "kind": "income", "monthly_cents": 200000})
                task("alice", "upsert_cashflow", {"id": "rent", "label": "Rent", "kind": "expense", "monthly_cents": 100000})
                statement = f"posted_on,amount_cents,direction,category,description,account_id,source_id\n{today},1250,expense,food,Shop,bank,one\n"
                self.assertEqual(task("alice", "import_csv", {"csv_text": statement})["saved"], 0)
                self.assertEqual(task("alice", "import_csv", {"csv_text": statement, "dry_run": False, "approved": True})["saved"], 1)
                self.assertEqual(task("alice", "spending_report", {"month": today[:7]})["expenses_cents"], 1250)
                self.assertEqual(task("alice", "overview", assumptions={"annual_return_bps": 0, "annual_inflation_bps": 0, "years": [1]})["trajectory"][0]["base_cents_real"], 1500000)
                task("alice", "pin_quote_widget", {"id": "widget", "symbol": "ABC", "display_name": "ABC"})
                exported = task("alice", "export_user_data")
                self.assertEqual(exported["schema_version"], SCHEMA_VERSION)
                self.assertEqual(len(exported["tables"]["transactions"]), 1)
                self.assertEqual(len(exported["tables"]["quote_widgets"]), 1)
                self.assertTrue(all(row["user_id"] == "alice" for rows in exported["tables"].values() for row in rows))
                with self.assertRaisesRegex(ValueError, "confirm"):
                    task("alice", "delete_user_data", {"confirm": "ERASE bob"})
                erased = task("alice", "delete_user_data", {"confirm": "ERASE alice"})
                self.assertTrue(erased["erased"])
                self.assertEqual(task("alice", "list_quote_widgets")["widgets"], [])
                self.assertEqual(task("bob", "overview")["net_worth_cents"], 300000)
                self.assertIsNone(db.execute("SELECT 1 FROM profiles WHERE user_id='alice'").fetchone())
            with sqlite3.connect(path) as db:
                initialize(db)
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
                self.assertIsNone(db.execute("SELECT 1 FROM transactions WHERE user_id='alice'").fetchone())
                self.assertEqual(db.execute("SELECT count(*) FROM accounts WHERE user_id='bob'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
