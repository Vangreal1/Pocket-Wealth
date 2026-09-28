"""Tests for the generic bank-CSV mapper (wealth/features.py's map_bank_csv, wired into
import_csv via an optional `mapping` payload) - added 2026-09-28 so a real bank's own CSV
export (its own column names, date format, and amount convention) can be imported without
needing to already match Wealth's internal schema. See README.md "Importing a bank statement"."""

import sqlite3
import unittest
from datetime import date

from wealth.core import execute, initialize
from wealth.features import map_bank_csv


class MapBankCsvUnitTests(unittest.TestCase):
    """Pure function tests - no db involved."""

    def test_signed_amount_mode_negative_is_expense_by_default(self):
        csv_text = "Date,Amount,Description\n01/15/2026,-42.50,Coffee Shop\n01/16/2026,1500.00,Payroll\n"
        mapping = {"posted_on": "Date", "date_format": "%m/%d/%Y", "description": "Description",
                  "account_id": "checking", "amount_mode": "signed", "amount_column": "Amount"}
        rows = map_bank_csv(csv_text, mapping)
        self.assertEqual(rows[0], {"posted_on": "2026-01-15", "amount_cents": 4250, "direction": "expense",
                                   "category": "uncategorized", "description": "Coffee Shop", "account_id": "checking"})
        self.assertEqual(rows[1]["direction"], "income")
        self.assertEqual(rows[1]["amount_cents"], 150000)

    def test_signed_amount_mode_can_invert_the_negative_convention(self):
        csv_text = "Date,Amount,Description\n01/15/2026,-42.50,Refund posted as negative\n"
        mapping = {"posted_on": "Date", "date_format": "%m/%d/%Y", "description": "Description",
                  "account_id": "checking", "amount_mode": "signed", "amount_column": "Amount",
                  "negative_means": "income"}
        rows = map_bank_csv(csv_text, mapping)
        self.assertEqual(rows[0]["direction"], "income")

    def test_debit_credit_mode_splits_by_which_column_has_a_value(self):
        csv_text = "Date,Debit,Credit,Description\n2026-01-15,42.50,,Coffee Shop\n2026-01-16,,1500.00,Payroll\n"
        mapping = {"posted_on": "Date", "description": "Description", "account_id": "checking",
                  "amount_mode": "debit_credit", "debit_column": "Debit", "credit_column": "Credit"}
        rows = map_bank_csv(csv_text, mapping)
        self.assertEqual((rows[0]["amount_cents"], rows[0]["direction"]), (4250, "expense"))
        self.assertEqual((rows[1]["amount_cents"], rows[1]["direction"]), (150000, "income"))

    def test_debit_credit_mode_rejects_a_row_with_both_values(self):
        csv_text = "Date,Debit,Credit,Description\n2026-01-15,42.50,10.00,Weird row\n"
        mapping = {"posted_on": "Date", "description": "Description", "account_id": "checking",
                  "amount_mode": "debit_credit", "debit_column": "Debit", "credit_column": "Credit"}
        with self.assertRaisesRegex(ValueError, "both a debit and a credit"):
            map_bank_csv(csv_text, mapping)

    def test_debit_credit_mode_rejects_a_row_with_neither_value(self):
        csv_text = "Date,Debit,Credit,Description\n2026-01-15,,,Empty row\n"
        mapping = {"posted_on": "Date", "description": "Description", "account_id": "checking",
                  "amount_mode": "debit_credit", "debit_column": "Debit", "credit_column": "Credit"}
        with self.assertRaisesRegex(ValueError, "neither a debit nor a credit"):
            map_bank_csv(csv_text, mapping)

    def test_unsigned_with_type_mode_maps_type_values_case_insensitively(self):
        csv_text = "Date,Amount,Type,Description\n2026-01-15,42.50,DEBIT,Coffee Shop\n2026-01-16,1500.00,credit,Payroll\n"
        mapping = {"posted_on": "Date", "description": "Description", "account_id": "checking",
                  "amount_mode": "unsigned_with_type", "amount_column": "Amount", "type_column": "Type",
                  "expense_values": ["Debit"], "income_values": ["Credit"]}
        rows = map_bank_csv(csv_text, mapping)
        self.assertEqual(rows[0]["direction"], "expense")
        self.assertEqual(rows[1]["direction"], "income")

    def test_unsigned_with_type_mode_rejects_an_unrecognized_type_value(self):
        csv_text = "Date,Amount,Type,Description\n2026-01-15,42.50,Fee,Mystery charge\n"
        mapping = {"posted_on": "Date", "description": "Description", "account_id": "checking",
                  "amount_mode": "unsigned_with_type", "amount_column": "Amount", "type_column": "Type",
                  "expense_values": ["Debit"], "income_values": ["Credit"]}
        with self.assertRaisesRegex(ValueError, "matches neither"):
            map_bank_csv(csv_text, mapping)

    def test_amount_parsing_handles_dollar_signs_thousands_separators_and_parens(self):
        csv_text = "Date,Amount,Description\n2026-01-15,\"$1,234.56\",Big purchase\n2026-01-16,(42.50),Parenthesized negative\n"
        mapping = {"posted_on": "Date", "description": "Description", "account_id": "checking",
                  "amount_mode": "signed", "amount_column": "Amount"}
        rows = map_bank_csv(csv_text, mapping)
        self.assertEqual(rows[0]["amount_cents"], 123456)
        self.assertEqual(rows[0]["direction"], "income")
        self.assertEqual(rows[1]["amount_cents"], 4250)
        self.assertEqual(rows[1]["direction"], "expense")

    def test_amount_parsing_rounds_correctly_instead_of_float_drift(self):
        # A classic float trap: 19.99 * 100 can land on 1998.9999999999998 in plain float math.
        csv_text = "Date,Amount,Description\n2026-01-15,19.99,Exact cents\n"
        mapping = {"posted_on": "Date", "description": "Description", "account_id": "checking",
                  "amount_mode": "signed", "amount_column": "Amount"}
        rows = map_bank_csv(csv_text, mapping)
        self.assertEqual(rows[0]["amount_cents"], 1999)

    def test_account_id_can_come_from_a_column_instead_of_a_literal(self):
        csv_text = "Date,Amount,Description,Account\n2026-01-15,42.50,Coffee,checking-1234\n"
        mapping = {"posted_on": "Date", "description": "Description", "account_id_column": "Account",
                  "amount_mode": "signed", "amount_column": "Amount"}
        rows = map_bank_csv(csv_text, mapping)
        self.assertEqual(rows[0]["account_id"], "checking-1234")

    def test_category_column_is_optional_and_falls_back_to_uncategorized(self):
        csv_text = "Date,Amount,Description\n2026-01-15,42.50,Coffee\n"
        mapping = {"posted_on": "Date", "description": "Description", "account_id": "checking",
                  "amount_mode": "signed", "amount_column": "Amount"}
        rows = map_bank_csv(csv_text, mapping)
        self.assertEqual(rows[0]["category"], "uncategorized")

    def test_a_custom_date_format_is_required_for_non_iso_dates(self):
        csv_text = "Date,Amount,Description\n01/15/2026,42.50,Coffee\n"
        mapping = {"posted_on": "Date", "description": "Description", "account_id": "checking",
                  "amount_mode": "signed", "amount_column": "Amount"}  # no date_format
        with self.assertRaisesRegex(ValueError, "date_format"):
            map_bank_csv(csv_text, mapping)

    def test_missing_required_mapping_key_gives_a_clear_error(self):
        csv_text = "Date,Amount,Description\n2026-01-15,42.50,Coffee\n"
        mapping = {"description": "Description", "account_id": "checking",
                  "amount_mode": "signed", "amount_column": "Amount"}  # no posted_on
        with self.assertRaisesRegex(ValueError, "mapping.posted_on"):
            map_bank_csv(csv_text, mapping)

    def test_a_mapped_column_not_present_in_the_csv_gives_a_clear_error(self):
        csv_text = "Date,Amount,Description\n2026-01-15,42.50,Coffee\n"
        mapping = {"posted_on": "Transaction Date", "description": "Description", "account_id": "checking",
                  "amount_mode": "signed", "amount_column": "Amount"}
        with self.assertRaisesRegex(ValueError, "no column named 'Transaction Date'"):
            map_bank_csv(csv_text, mapping)

    def test_an_unknown_amount_mode_is_rejected(self):
        csv_text = "Date,Amount,Description\n2026-01-15,42.50,Coffee\n"
        mapping = {"posted_on": "Date", "description": "Description", "account_id": "checking",
                  "amount_mode": "not_a_real_mode"}
        with self.assertRaisesRegex(ValueError, "amount_mode"):
            map_bank_csv(csv_text, mapping)

    def test_missing_account_id_and_account_id_column_is_rejected(self):
        csv_text = "Date,Amount,Description\n2026-01-15,42.50,Coffee\n"
        mapping = {"posted_on": "Date", "description": "Description",
                  "amount_mode": "signed", "amount_column": "Amount"}
        with self.assertRaisesRegex(ValueError, "account_id"):
            map_bank_csv(csv_text, mapping)


class MappedImportIntegrationTests(unittest.TestCase):
    """Confirms a mapped import goes through the same add_transactions() review/dedup/approval
    path a manual import does - it's a format conversion, not a separate save path."""

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        initialize(self.db)
        execute(self.db, {"user_id": "a", "task_id": "profile-setup", "action": "upsert_profile",
                          "data": {"currency": "USD", "timezone": "UTC", "tax_jurisdiction": "US"}})
        self.seq = 0

    def tearDown(self):
        self.db.close()

    def task(self, action, data=None, user="a"):
        self.seq += 1
        payload = {"task_id": str(self.seq), "user_id": user, "action": action}
        if data is not None:
            payload["data"] = data
        return execute(self.db, payload)["result"]

    def test_a_mapped_import_still_requires_dry_run_review_before_saving(self):
        day = date.today().replace(day=1).strftime("%m/%d/%Y")
        csv_text = f"Date,Amount,Description\n{day},-42.50,Coffee Shop\n"
        mapping = {"posted_on": "Date", "date_format": "%m/%d/%Y", "description": "Description",
                  "account_id": "checking", "amount_mode": "signed", "amount_column": "Amount"}
        preview = self.task("import_csv", {"csv_text": csv_text, "mapping": mapping})
        self.assertEqual(preview["saved"], 0)
        self.assertTrue(preview["review_required"])
        with self.assertRaisesRegex(ValueError, "approved"):
            self.task("import_csv", {"csv_text": csv_text, "mapping": mapping, "dry_run": False})
        saved = self.task("import_csv", {"csv_text": csv_text, "mapping": mapping, "dry_run": False, "approved": True})
        self.assertEqual(saved["saved"], 1)

    def test_a_mapped_import_deduplicates_against_an_identical_manual_entry(self):
        # The mapped CSV below has no category column, so it lands in "uncategorized" - the
        # manual entry below matches that exactly so the two rows fingerprint identically and
        # this genuinely exercises dedup, not just two unrelated rows that happen not to collide.
        day = date.today().replace(day=1)
        manual_csv = f"posted_on,amount_cents,direction,category,description,account_id\n{day.isoformat()},4250,expense,uncategorized,Coffee Shop,checking\n"
        self.task("import_csv", {"csv_text": manual_csv, "dry_run": False, "approved": True})
        bank_csv = f"Date,Amount,Description\n{day.strftime('%m/%d/%Y')},-42.50,Coffee Shop\n"
        mapping = {"posted_on": "Date", "date_format": "%m/%d/%Y", "description": "Description",
                  "account_id": "checking", "amount_mode": "signed", "amount_column": "Amount"}
        result = self.task("import_csv", {"csv_text": bank_csv, "mapping": mapping, "dry_run": False, "approved": True})
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["saved"], 0)


if __name__ == "__main__":
    unittest.main()
