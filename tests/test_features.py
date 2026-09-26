import sqlite3
import unittest
from datetime import date

from wealth.core import execute, initialize


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        initialize(self.db)
        execute(self.db, {"user_id": "a", "task_id": "profile-setup", "action": "upsert_profile",
                          "data": {"currency": "USD", "timezone": "UTC", "tax_jurisdiction": "US"}})
        self.seq = 0

    def tearDown(self):
        self.db.close()

    def task(self, action, data=None, user="a", assumptions=None):
        self.seq += 1
        payload = {"task_id": str(self.seq), "user_id": user, "action": action}
        if data is not None:
            payload["data"] = data
        if assumptions is not None:
            payload["assumptions"] = assumptions
        return execute(self.db, payload)["result"]

    def test_import_review_dedup_and_spending(self):
        day = date.today().replace(day=1).isoformat()
        csv_text = f"posted_on,amount_cents,direction,category,description,account_id,source_id\n{day},1500,expense,groceries,Market,checking,statement-1\n{day},1000,transfer,savings,Transfer,checking,statement-2\n"
        preview = self.task("import_csv", {"csv_text": csv_text})
        self.assertEqual(preview["saved"], 0)
        self.assertEqual(self.task("spending_report", {"month": day[:7]})["transactions"], 0)
        with self.assertRaisesRegex(ValueError, "approved"):
            self.task("import_csv", {"csv_text": csv_text, "dry_run": False})
        self.assertEqual(self.task("import_csv", {"csv_text": csv_text, "dry_run": False, "approved": True})["saved"], 2)
        self.assertEqual(self.task("import_csv", {"csv_text": csv_text, "dry_run": False, "approved": True})["duplicates"], 2)
        result = self.task("spending_report", {"month": day[:7]})
        self.assertEqual(result["expenses_cents"], 1500)
        self.assertEqual(result["transfers_excluded_cents"], 1000)
        self.assertEqual(result["expense_categories_cents"]["groceries"], 1500)
        self.task("upsert_budget", {"category": "groceries", "monthly_limit_cents": 1200})
        self.assertEqual(self.task("spending_report", {"month": day[:7]})["budgets"][0]["remaining_cents"], -300)
        trends = self.task("spending_trends", {"months": 1})
        self.assertEqual(trends["total_expenses_cents"], 1500)
        self.assertEqual(self.task("spending_report", {"month": day[:7]}, user="b")["expenses_cents"], 0)

    def test_seasonal_income_changes_trajectory(self):
        self.task("upsert_account", {"id": "cash", "name": "cash", "kind": "cash", "balance_cents": 1000, "as_of": date.today().isoformat()})
        for month in range(1, 13):
            self.task("upsert_seasonal", {"month": month, "income_cents": 20000 if month <= 9 else 0, "expense_cents": 10000})
        view = self.task("overview", assumptions={"annual_return_bps": 0, "annual_inflation_bps": 0, "years": [1]})
        self.assertTrue(view["monthly_values_are_annual_averages"])
        self.assertEqual(view["annual_income_cents"], 180000)
        self.assertEqual(view["annual_expenses_cents"], 120000)
        self.assertEqual(view["trajectory"][0]["base_cents_real"], 61000)
        self.assertEqual(len(view["next_12_months"]), 12)

    def test_seasonal_shortfall_flag(self):
        self.task("upsert_account", {"id": "cash", "name": "cash", "kind": "cash", "balance_cents": 1000, "as_of": date.today().isoformat()})
        for month in range(1, 13):
            self.task("upsert_seasonal", {"month": month, "income_cents": 0 if month == date.today().month else 20000, "expense_cents": 10000})
        view = self.task("overview")
        self.assertGreater(view["annual_income_cents"], view["annual_expenses_cents"])
        self.assertEqual(view["next_12_months"][0]["estimated_end_cash_cents"], -9000)
        self.assertIn("Plan for a projected cash shortfall", [r["title"] for r in view["recommendations"]])

    def test_loan_amortization_and_tax_organization(self):
        self.task("upsert_account", {"id": "car", "name": "car loan", "kind": "debt", "balance_cents": 1200000, "apr_bps": 600, "as_of": date.today().isoformat()})
        self.task("upsert_loan_terms", {"account_id": "car", "payment_cents": 52000})
        loan = self.task("loan_analysis", {"account_id": "car", "extra_cents": 20000})
        self.assertLess(loan["with_extra"]["payoff_months"], loan["baseline"]["payoff_months"])
        self.assertLess(loan["with_extra"]["total_interest_cents"], loan["baseline"]["total_interest_cents"])
        quotes = self.task("compare_loan_quotes", {"principal_cents": 1000000, "quotes": [
            {"name": "A", "interest_rate_bps": 500, "term_months": 36, "upfront_fees_cents": 5000},
            {"name": "B", "interest_rate_bps": 700, "term_months": 36}]})
        self.assertEqual(len(quotes["offers"]), 2)
        self.assertGreater(quotes["offers"][1]["estimated_total_cost_cents"], quotes["offers"][0]["estimated_total_cost_cents"])
        plan = self.task("debt_plan", {"extra_budget_cents": 20000})
        self.assertIsNotNone(plan["avalanche"]["payoff_months"])
        with self.assertRaisesRegex(ValueError, "different request"):
            execute(self.db, {"task_id": "1", "user_id": "a", "action": "loan_analysis", "data": {"account_id": "car"}})
        self.task("upsert_tax_item", {"id": "w2", "tax_year": date.today().year, "kind": "wages", "amount_cents": 5000000})
        tax = self.task("tax_organizer", {"tax_year": date.today().year})
        self.assertEqual(tax["totals_cents"]["wages"], 5000000)
        self.assertEqual(tax["status"], "organization_only")
        self.assertEqual(self.task("tax_organizer", {"tax_year": date.today().year}, user="b")["totals_cents"], {})

    def test_paper_orders_are_simulated_and_isolated(self):
        self.task("paper_open", {"starting_cash_cents": 100000})
        buy = self.task("paper_order", {"symbol": "ABC", "side": "buy", "quantity": 10,
                                        "price_cents": 1000, "fee_cents": 100})
        self.assertTrue(buy["paper_only"])
        self.assertEqual(buy["cash_cents"], 89900)
        with self.assertRaisesRegex(ValueError, "paper account"):
            self.task("paper_portfolio", user="b")
        sale = self.task("paper_order", {"symbol": "ABC", "side": "sell", "quantity": 10,
                                         "price_cents": 1200, "fee_cents": 100})
        self.assertEqual(sale["realized_pnl_cents"], 1800)
        self.assertEqual(self.task("paper_portfolio")["positions"], [])
        with self.assertRaisesRegex(ValueError, "paper shares"):
            self.task("paper_order", {"symbol": "ABC", "side": "sell", "quantity": 1, "price_cents": 1200})

    def test_debt_methods_and_retirement_scenario(self):
        for id_, balance, rate, minimum in (("small", 100000, 500, 5000), ("expensive", 300000, 2400, 10000)):
            self.task("upsert_account", {"id": id_, "name": id_, "kind": "debt", "balance_cents": balance,
                                         "apr_bps": rate, "as_of": date.today().isoformat()})
            self.task("upsert_loan_terms", {"account_id": id_, "payment_cents": minimum})
        plan = self.task("debt_plan", {"extra_budget_cents": 10000})
        self.assertLessEqual(plan["avalanche"]["interest_cents"], plan["snowball"]["interest_cents"])
        self.task("upsert_account", {"id": "401k", "name": "401k", "kind": "investment",
                                     "balance_cents": 1000000, "as_of": date.today().isoformat()})
        result = self.task("retirement_scenario", {"current_age": 46, "retirement_age": 66,
                                                   "monthly_saving_cents": 50000, "target_monthly_spending_cents": 400000,
                                                   "annual_return_bps": 0, "annual_inflation_bps": 0})
        self.assertEqual(result["projected_portfolio_cents_real"], 13000000)
        self.assertNotIn("illustrative_monthly_portfolio_draw_cents_real", result)


if __name__ == "__main__":
    unittest.main()
