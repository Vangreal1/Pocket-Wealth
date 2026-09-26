import sqlite3
import unittest

from wealth.core import execute, initialize


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        initialize(self.db)
        execute(self.db, {"user_id": "a", "task_id": "profile-setup", "action": "upsert_profile",
                          "data": {"currency": "USD", "timezone": "UTC", "tax_jurisdiction": "US"}})
        self.counter = 0

    def tearDown(self):
        self.db.close()

    def run_task(self, action, data=None, user="a", **kwargs):
        self.counter += 1
        payload = {"user_id": user, "task_id": str(self.counter), "action": action}
        if data is not None:
            payload["data"] = data
        payload.update(kwargs)
        return execute(self.db, payload)["result"]

    def test_trajectory_and_advice(self):
        self.run_task("upsert_account", {"id": "cash", "name": "cash", "kind": "cash", "balance_cents": 100000, "as_of": "2026-01-01"})
        self.run_task("upsert_account", {"id": "loan", "name": "loan", "kind": "debt", "balance_cents": 200000, "apr_bps": 1500, "as_of": "2026-01-01"})
        self.run_task("upsert_cashflow", {"id": "pay", "label": "pay", "kind": "income", "monthly_cents": 400000})
        self.run_task("upsert_cashflow", {"id": "bills", "label": "bills", "kind": "expense", "monthly_cents": 300000})
        view = self.run_task("overview", assumptions={"annual_return_bps": 0, "annual_inflation_bps": 0, "years": [1]})
        self.assertEqual(view["net_worth_cents"], -100000)
        self.assertEqual(view["monthly_surplus_cents"], 100000)
        self.assertEqual(view["trajectory"][0]["base_cents_real"], 1100000)
        self.assertEqual(view["trajectory_status"], "available")
        self.assertEqual(view["trajectory_assessment"]["direction"], "improving_under_assumptions")
        self.assertIn("Review high-rate debt", [x["title"] for x in view["recommendations"]])
        # Regression: this exact case (a high-rate debt present, which populates the "Review
        # high-rate debt" recommendation above) used to silently clobber `high_rate` - the int
        # return-rate variable computed earlier in the same function for the scenario's upper
        # bound - with the *list* of high-rate debt accounts built for that recommendation,
        # because both used the same variable name. assumptions.annual_return_bps=0 here, so the
        # correct higher_annual_return_bps is max(600, 0+500)=600, an int; the bug returned [].
        self.assertEqual(view["assumptions"]["higher_annual_return_bps"], 600)

    def test_user_isolation_and_idempotency(self):
        payload = {"user_id": "a", "task_id": "once", "action": "upsert_account", "data": {"id": "x", "name": "x", "kind": "cash", "balance_cents": 500, "as_of": "2026-01-01"}}
        first = execute(self.db, payload)
        self.assertEqual(first, execute(self.db, payload))
        payload["data"]["balance_cents"] = 600
        with self.assertRaisesRegex(ValueError, "different request"):
            execute(self.db, payload)
        self.assertEqual(self.run_task("overview")["net_worth_cents"], 500)
        self.assertEqual(self.run_task("overview", user="b")["net_worth_cents"], 0)

    def test_missing_data_withholds_trajectory(self):
        view = self.run_task("overview")
        self.assertEqual(view["trajectory"], [])
        self.assertEqual(view["trajectory_status"], "insufficient_data")
        self.assertEqual(view["trajectory_assessment"]["direction"], "unknown")
        self.assertEqual(view["recommendations"][0]["priority"], "first")

    def test_investment_only_on_explicit_amount(self):
        self.run_task("upsert_account", {"id": "invest", "name": "invest", "kind": "investment", "balance_cents": 100000, "as_of": "2026-01-01"})
        self.run_task("upsert_cashflow", {"id": "pay", "label": "pay", "kind": "income", "monthly_cents": 20000})
        self.run_task("upsert_cashflow", {"id": "bills", "label": "bills", "kind": "expense", "monthly_cents": 10000})
        cash = self.run_task("overview", assumptions={"annual_return_bps": 10000, "annual_inflation_bps": 0, "monthly_investment_cents": 0, "years": [1]})
        invested = self.run_task("overview", assumptions={"annual_return_bps": 10000, "annual_inflation_bps": 0, "monthly_investment_cents": 10000, "years": [1]})
        self.assertEqual(cash["trajectory"][0]["base_cents_real"], 320000)
        self.assertGreater(invested["trajectory"][0]["base_cents_real"], 320000)
        with self.assertRaisesRegex(ValueError, "monthly surplus"):
            self.run_task("overview", assumptions={"monthly_investment_cents": 10001})

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.run_task("upsert_cashflow", {"id": "x", "label": "x", "kind": "expense", "monthly_cents": True})
        with self.assertRaises(ValueError):
            self.run_task("overview", assumptions={"years": [0]})
        with self.assertRaises(ValueError):
            self.run_task("upsert_account", {"id": "x", "name": "x", "kind": "cash", "balance_cents": 1, "as_of": "2026-01-01", "source": "bank_verified"})

    def test_generic_user_settings_and_currency_boundary(self):
        with self.assertRaisesRegex(ValueError, "profile"):
            self.run_task("upsert_cashflow", {"id": "salary", "label": "salary", "kind": "income", "monthly_cents": 100}, user="b")
        self.run_task("upsert_profile", {"currency": "EUR", "timezone": "Europe/Berlin", "tax_jurisdiction": "DE"}, user="b")
        self.run_task("upsert_account", {"id": "bank", "name": "bank", "kind": "cash", "balance_cents": 500, "as_of": "2026-01-01"}, user="b")
        self.assertEqual(self.run_task("overview", user="b")["profile"]["currency"], "EUR")
        self.assertEqual(self.run_task("overview")["profile"]["currency"], "USD")
        with self.assertRaisesRegex(ValueError, "cannot change"):
            self.run_task("upsert_profile", {"currency": "USD", "timezone": "Europe/Berlin", "tax_jurisdiction": "DE"}, user="b")
        with self.assertRaisesRegex(ValueError, "two-decimal"):
            self.run_task("upsert_profile", {"currency": "JPY", "timezone": "Asia/Tokyo", "tax_jurisdiction": "JP"}, user="c")

    def test_legacy_currency_requires_review(self):
        self.db.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)",
                        ("legacy", "bank", "bank", "cash", 1000, 0, "2026-01-01", "manual"))
        with self.assertRaisesRegex(ValueError, "confirm_legacy_currency"):
            self.run_task("upsert_profile", {"currency": "EUR", "timezone": "UTC", "tax_jurisdiction": "DE"}, user="legacy")
        result = self.run_task("upsert_profile", {"currency": "EUR", "timezone": "UTC", "tax_jurisdiction": "DE", "confirm_legacy_currency": True}, user="legacy")
        self.assertEqual(result["currency"], "EUR")


if __name__ == "__main__":
    unittest.main()
