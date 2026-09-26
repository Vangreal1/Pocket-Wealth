"""Manual financial workflows. Inputs are unverified until reviewed by the user."""
import csv
import hashlib
import io
from collections import defaultdict
from datetime import date
from . import profile


def integer(value, label, minimum=0, maximum=10**15):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer in [{minimum}, {maximum}]")
    return value


def string(value, label, limit=100):
    if not isinstance(value, str) or not 1 <= len(value) <= limit or not value.strip():
        raise ValueError(f"{label} must be a nonempty string of at most {limit} characters")
    return value.strip()


def iso_date(value, label="date", today=None):
    value = string(value, label, 10)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date") from exc
    if parsed > (today or date.today()):
        raise ValueError(f"{label} cannot be in the future")
    return value


def ensure_tables(db):
    ddl = """
      CREATE TABLE IF NOT EXISTS transactions (
        user_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
        posted_on TEXT NOT NULL, amount_cents INTEGER NOT NULL,
        direction TEXT NOT NULL, category TEXT NOT NULL,
        description TEXT NOT NULL, account_id TEXT NOT NULL,
        source TEXT NOT NULL, PRIMARY KEY(user_id,fingerprint));
      CREATE INDEX IF NOT EXISTS transactions_user_date ON transactions(user_id,posted_on);
      CREATE TABLE IF NOT EXISTS seasonal (
        user_id TEXT NOT NULL, month INTEGER NOT NULL,
        income_cents INTEGER NOT NULL, expense_cents INTEGER NOT NULL,
        PRIMARY KEY(user_id,month));
      CREATE TABLE IF NOT EXISTS loan_terms (
        user_id TEXT NOT NULL, account_id TEXT NOT NULL,
        payment_cents INTEGER NOT NULL,
        PRIMARY KEY(user_id,account_id));
      CREATE TABLE IF NOT EXISTS tax_items (
        user_id TEXT NOT NULL, id TEXT NOT NULL,
        tax_year INTEGER NOT NULL, kind TEXT NOT NULL,
        amount_cents INTEGER NOT NULL, note TEXT NOT NULL,
        PRIMARY KEY(user_id,id));
      CREATE TABLE IF NOT EXISTS budgets (
        user_id TEXT NOT NULL, category TEXT NOT NULL,
        monthly_limit_cents INTEGER NOT NULL,
        PRIMARY KEY(user_id,category));
      CREATE TABLE IF NOT EXISTS paper_accounts (
        user_id TEXT PRIMARY KEY, cash_cents INTEGER NOT NULL,
        realized_pnl_cents INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS paper_positions (
        user_id TEXT NOT NULL, symbol TEXT NOT NULL,
        quantity INTEGER NOT NULL, cost_cents INTEGER NOT NULL,
        last_price_cents INTEGER NOT NULL, PRIMARY KEY(user_id,symbol));
      CREATE TABLE IF NOT EXISTS paper_orders (
        user_id TEXT NOT NULL, task_id TEXT NOT NULL,
        symbol TEXT NOT NULL, side TEXT NOT NULL,
        quantity INTEGER NOT NULL, price_cents INTEGER NOT NULL,
        fee_cents INTEGER NOT NULL, PRIMARY KEY(user_id,task_id));
    """
    for statement in ddl.split(";"):
        if statement.strip():
            db.execute(statement)


def validate_transaction(row, today):
    if not isinstance(row, dict):
        raise ValueError("transaction must be an object")
    direction = row.get("direction")
    if direction not in {"income", "expense", "transfer"}:
        raise ValueError("direction must be income, expense or transfer")
    values = (iso_date(row.get("posted_on"), "posted_on", today),
              integer(row.get("amount_cents"), "amount_cents", 1), direction,
              string(row.get("category"), "category"),
              string(row.get("description"), "description", 200),
              string(row.get("account_id"), "account_id"))
    # Exact duplicate bank rows can exist. Require a unique statement row ID for
    # imports where two equal transactions occur on the same day.
    source_id = row.get("source_id")
    if source_id is None:
        source_id = "|".join(map(str, values))
    else:
        source_id = string(source_id, "source_id", 200)
    fingerprint = hashlib.sha256((values[5] + "|" + source_id).encode()).hexdigest()
    return (fingerprint, *values)


def add_transactions(db, user, data):
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise ValueError("rows must be a list")
    rows = data["rows"]
    if not 1 <= len(rows) <= 200:
        raise ValueError("1–200 transactions per request")
    dry_run = data.get("dry_run", True)
    if type(dry_run) is not bool:
        raise ValueError("dry_run must be boolean")
    if not dry_run and data.get("approved") is not True:
        raise ValueError("explicit approved:true required to save imported transactions")
    today = profile.local_today(db, user)
    validated = [validate_transaction(row, today) for row in rows]
    fingerprints = [row[0] for row in validated]
    existing = {row[0] for fingerprint in set(fingerprints) for row in db.execute(
        "SELECT fingerprint FROM transactions WHERE user_id=? AND fingerprint=?", (user, fingerprint))}
    seen = set(existing)
    new = []
    for row in validated:
        if row[0] not in seen:
            new.append(row)
            seen.add(row[0])
    if not dry_run:
        db.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?)",
                       [(user, *row, "csv" if data.get("format") == "csv" else "manual") for row in new])
    return {"submitted": len(rows), "new": len(new), "duplicates": len(rows)-len(new),
            "saved": 0 if dry_run else len(new), "dry_run": dry_run,
            "review_required": dry_run}


def import_csv(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    body = data.get("csv_text")
    if not isinstance(body, str) or not body or len(body) > 50000:
        raise ValueError("csv_text must be 1–50000 characters")
    reader = csv.DictReader(io.StringIO(body))
    required = {"posted_on", "amount_cents", "direction", "category", "description", "account_id"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("CSV needs posted_on,amount_cents,direction,category,description,account_id headers")
    rows = []
    for row in reader:
        if len(rows) >= 200:
            raise ValueError("CSV exceeds 200 rows")
        if None in row:
            raise ValueError("CSV row has extra columns")
        row["amount_cents"] = int(row["amount_cents"]) if row["amount_cents"].isdigit() else row["amount_cents"]
        rows.append(row)
    return add_transactions(db, user, {"rows": rows, "dry_run": data.get("dry_run", True),
                                       "approved": data.get("approved", False), "format": "csv"})


def spending_report(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    period = string(data.get("month"), "month", 7)
    try:
        date.fromisoformat(period + "-01")
    except ValueError as exc:
        raise ValueError("month must be YYYY-MM") from exc
    rows = db.execute("SELECT direction,category,amount_cents FROM transactions WHERE user_id=? AND substr(posted_on,1,7)=?", (user, period)).fetchall()
    categories = defaultdict(int)
    income = expenses = transfers = 0
    for direction, category, amount in rows:
        if direction == "expense":
            expenses += amount
            categories[category] += amount
        elif direction == "income":
            income += amount
        else:
            transfers += amount
    budget_rows = db.execute("SELECT category,monthly_limit_cents FROM budgets WHERE user_id=?", (user,)).fetchall()
    budgets = [{"category": category, "limit_cents": limit, "spent_cents": categories[category],
                "remaining_cents": limit-categories[category]} for category, limit in budget_rows]
    return {"month": period, "transactions": len(rows), "income_cents": income,
            "expenses_cents": expenses, "net_cents": income-expenses,
            "transfers_excluded_cents": transfers, "expense_categories_cents": dict(sorted(categories.items())),
            "budgets": budgets,
            "warning": "Manual/imported entries may omit cash spending or contain uncategorized transfers."}


def spending_trends(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    months = integer(data.get("months", 12), "months", 1, 36)
    today = profile.local_today(db, user)
    periods = [f"{today.year + (today.month-1-offset)//12:04d}-{(today.month-1-offset)%12+1:02d}" for offset in reversed(range(months))]
    rows = db.execute("SELECT substr(posted_on,1,7), direction, sum(amount_cents), count(*) FROM transactions WHERE user_id=? AND substr(posted_on,1,7)>=? GROUP BY 1,2", (user, periods[0])).fetchall()
    totals = {p: {"month": p, "income_cents": 0, "expenses_cents": 0, "transaction_count": 0} for p in periods}
    for period, direction, amount, count in rows:
        if period in totals:
            if direction in {"income", "expense"}:
                totals[period]["income_cents" if direction == "income" else "expenses_cents"] += amount
            totals[period]["transaction_count"] += count
    result = list(totals.values())
    return {"months": result, "total_expenses_cents": sum(m["expenses_cents"] for m in result),
            "average_expenses_cents_for_months_with_entries": (
                round(sum(m["expenses_cents"] for m in result) / sum(m["transaction_count"] > 0 for m in result))
                if any(m["transaction_count"] for m in result) else None),
            "warning": "Months without imported transactions mean no data, not zero spending. Partial account coverage distorts trends."}


def upsert_budget(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    category = string(data.get("category"), "category")
    limit = integer(data.get("monthly_limit_cents"), "monthly_limit_cents")
    db.execute("INSERT INTO budgets VALUES (?,?,?) ON CONFLICT(user_id,category) DO UPDATE SET monthly_limit_cents=excluded.monthly_limit_cents", (user, category, limit))
    return {"category": category, "saved": True}


def upsert_seasonal(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    month = integer(data.get("month"), "month", 1, 12)
    income = integer(data.get("income_cents"), "income_cents")
    expense = integer(data.get("expense_cents"), "expense_cents")
    db.execute("INSERT INTO seasonal VALUES (?,?,?,?) ON CONFLICT(user_id,month) DO UPDATE SET income_cents=excluded.income_cents,expense_cents=excluded.expense_cents", (user, month, income, expense))
    return {"month": month, "saved": True}


def seasonal_profile(db, user):
    rows = {m: (inc, exp) for m, inc, exp in db.execute(
        "SELECT month,income_cents,expense_cents FROM seasonal WHERE user_id=?", (user,))}
    return rows


def upsert_loan_terms(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    account_id = string(data.get("account_id"), "account_id")
    account = db.execute("SELECT kind FROM accounts WHERE user_id=? AND id=?", (user, account_id)).fetchone()
    if not account or account[0] != "debt":
        raise ValueError("loan terms require an existing debt account")
    payment = integer(data.get("payment_cents"), "payment_cents", 1)
    db.execute("INSERT INTO loan_terms VALUES (?,?,?) ON CONFLICT(user_id,account_id) DO UPDATE SET payment_cents=excluded.payment_cents", (user, account_id, payment))
    return {"account_id": account_id, "saved": True}


def amortize(principal, apr_bps, payment, extra=0):
    principal = integer(principal, "principal_cents")
    apr_bps = integer(apr_bps, "apr_bps", 0, 100000)
    payment = integer(payment, "payment_cents", 1)
    extra = integer(extra, "extra_cents")
    balance = principal
    interest_total = 0
    for month in range(1, 601):
        if balance == 0:
            return {"payoff_months": month-1, "total_interest_cents": interest_total,
                    "total_paid_cents": principal+interest_total}
        interest = (balance * apr_bps + 60000) // 120000  # nearest cent
        if payment+extra <= interest:
            return {"payoff_months": None, "reason": "Payment does not cover monthly interest"}
        balance -= min(balance, payment+extra-interest)
        interest_total += interest
    return {"payoff_months": None, "reason": "Not paid off within 50 years"}


def loan_analysis(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    account_id = string(data.get("account_id"), "account_id")
    row = db.execute("SELECT balance_cents,apr_bps FROM accounts WHERE user_id=? AND id=? AND kind='debt'", (user, account_id)).fetchone()
    payment = db.execute("SELECT payment_cents FROM loan_terms WHERE user_id=? AND account_id=?", (user, account_id)).fetchone()
    if row is None or payment is None:
        raise ValueError("debt account and monthly payment required")
    extra = integer(data.get("extra_cents", 0), "extra_cents")
    baseline = amortize(*row, payment[0])
    accelerated = amortize(*row, payment[0], extra)
    return {"account_id": account_id, "balance_cents": row[0], "apr_bps": row[1],
            "payment_cents": payment[0], "extra_cents": extra, "baseline": baseline,
            "with_extra": accelerated, "warning": "Assumes fixed APR, monthly interest, no fees or payment changes. Verify lender terms."}


def debt_plan(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    extra = integer(data.get("extra_budget_cents", 0), "extra_budget_cents")
    accounts = db.execute("SELECT a.id,a.balance_cents,a.apr_bps,l.payment_cents FROM accounts a LEFT JOIN loan_terms l ON a.user_id=l.user_id AND a.id=l.account_id WHERE a.user_id=? AND a.kind='debt' AND a.balance_cents>0", (user,)).fetchall()
    if not accounts or any(row[3] is None for row in accounts):
        raise ValueError("all positive debt accounts need loan terms")
    def simulate(method):
        balances = {id_: balance for id_, balance, apr, payment in accounts}
        payments = {id_: payment for id_, balance, apr, payment in accounts}
        rates = {id_: apr for id_, balance, apr, payment in accounts}
        monthly_budget = sum(payments.values()) + extra
        interest_total = 0
        paid_off = {}
        for month in range(1, 601):
            active = [id_ for id_, balance in balances.items() if balance > 0]
            if not active:
                return {"method": method, "payoff_months": month-1,
                        "interest_cents": interest_total, "paid_off_at_month": paid_off}
            available = monthly_budget
            for id_ in active:
                interest = (balances[id_] * rates[id_] + 60000) // 120000
                if payments[id_] <= interest:
                    return {"method": method, "payoff_months": None,
                            "reason": f"{id_} minimum does not cover interest"}
                balances[id_] += interest
                interest_total += interest
                due = min(payments[id_], balances[id_])
                balances[id_] -= due
                available -= due
                if balances[id_] == 0:
                    paid_off[id_] = month
            targets = sorted((id_ for id_ in balances if balances[id_] > 0),
                             key=(lambda id_: (-rates[id_], balances[id_], id_)) if method == "avalanche"
                             else (lambda id_: (balances[id_], -rates[id_], id_)))
            for id_ in targets:
                applied = min(available, balances[id_])
                balances[id_] -= applied
                available -= applied
                if balances[id_] == 0:
                    paid_off[id_] = month
        return {"method": method, "payoff_months": None, "reason": "Not paid off within 50 years"}
    return {"extra_budget_cents": extra, "monthly_budget_cents": sum(row[3] for row in accounts)+extra,
            "avalanche": simulate("avalanche"), "snowball": simulate("snowball"),
            "warning": "Assumes fixed APR and payment budget, monthly interest, no new debt or fees. Check that the extra budget is affordable and verify loan terms."}


def compare_loan_quotes(db, user, data):
    """Compare user-entered fixed-rate offers; no live rate lookup."""
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    principal = integer(data.get("principal_cents"), "principal_cents", 1)
    quotes = data.get("quotes")
    if not isinstance(quotes, list) or not 1 <= len(quotes) <= 10:
        raise ValueError("quotes must contain 1–10 offers")
    results = []
    for quote in quotes:
        if not isinstance(quote, dict):
            raise ValueError("quote must be an object")
        name = string(quote.get("name"), "name")
        rate = integer(quote.get("interest_rate_bps"), "interest_rate_bps", 0, 100000)
        months = integer(quote.get("term_months"), "term_months", 1, 600)
        fees = integer(quote.get("upfront_fees_cents", 0), "upfront_fees_cents")
        monthly_rate = rate / 120000
        payment = (principal / months if monthly_rate == 0 else
                   principal * monthly_rate / (1 - (1 + monthly_rate) ** -months))
        rounded_payment = round(payment)
        total = round(payment * months) + fees
        results.append({"name": name, "interest_rate_bps": rate, "term_months": months,
                        "upfront_fees_cents": fees, "estimated_monthly_payment_cents": rounded_payment,
                        "estimated_total_cost_cents": total,
                        "estimated_finance_cost_cents": total-principal})
    return {"principal_cents": principal, "offers": results,
            "warning": "User-entered offers only; not live lender quotes. Estimate assumes fixed interest rate, full term, and fees paid upfront. Verify APR, fees, eligibility and early-payoff terms with each lender."}


TAX_KINDS = {"employment_income", "benefits", "wages", "unemployment", "self_employment",
             "interest", "dividends", "capital_gain", "withholding", "tax_payment",
             "federal_withholding", "state_withholding", "estimated_payment", "potential_deduction", "other"}


def upsert_tax_item(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    item_id = string(data.get("id"), "id")
    tax_year = integer(data.get("tax_year"), "tax_year", 2000, profile.local_today(db, user).year + 1)
    kind = data.get("kind")
    if kind not in TAX_KINDS:
        raise ValueError("invalid tax item kind")
    amount = integer(data.get("amount_cents"), "amount_cents")
    note = string(data.get("note", "user entry"), "note", 200)
    db.execute("INSERT INTO tax_items VALUES (?,?,?,?,?,?) ON CONFLICT(user_id,id) DO UPDATE SET tax_year=excluded.tax_year,kind=excluded.kind,amount_cents=excluded.amount_cents,note=excluded.note", (user, item_id, tax_year, kind, amount, note))
    return {"id": item_id, "saved": True}


def tax_organizer(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    year = integer(data.get("tax_year"), "tax_year", 2000, profile.local_today(db, user).year + 1)
    totals = defaultdict(int)
    for kind, amount in db.execute("SELECT kind,amount_cents FROM tax_items WHERE user_id=? AND tax_year=?", (user, year)):
        totals[kind] += amount
    return {"tax_year": year, "tax_jurisdiction": (profile.get(db, user) or {}).get("tax_jurisdiction"),
            "totals_cents": dict(sorted(totals.items())),
            "status": "organization_only", "warning": "These are user-entered totals, not verified forms or a tax liability estimate. Deductibility and applicable law require review."}


def retirement_scenario(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    current_age = integer(data.get("current_age"), "current_age", 18, 100)
    retirement_age = integer(data.get("retirement_age"), "retirement_age", current_age+1, min(110, current_age+50))
    years = retirement_age-current_age
    monthly_saving = integer(data.get("monthly_saving_cents"), "monthly_saving_cents")
    target = integer(data.get("target_monthly_spending_cents"), "target_monthly_spending_cents", 1)
    other = integer(data.get("other_monthly_income_cents", 0), "other_monthly_income_cents")
    ret = integer(data.get("annual_return_bps", 300), "annual_return_bps", -10000, 20000)
    inflation = integer(data.get("annual_inflation_bps", 250), "annual_inflation_bps", 0, 10000)
    invested = db.execute("SELECT coalesce(sum(balance_cents),0) FROM accounts WHERE user_id=? AND kind='investment'", (user,)).fetchone()[0]
    if not db.execute("SELECT 1 FROM accounts WHERE user_id=? AND kind='investment'", (user,)).fetchone():
        raise ValueError("at least one investment account required")
    monthly_rate = (1 + ret/10000) ** (1/12)-1
    future = invested
    for _ in range(years*12):
        future = future*(1+monthly_rate)+monthly_saving
    real_portfolio = round(future/(1+inflation/10000)**years)
    result = {"retirement_age": retirement_age, "years_until_retirement": years,
              "current_investments_cents": invested, "projected_portfolio_cents_real": real_portfolio,
              "target_monthly_spending_cents_real": target, "other_monthly_income_cents_real": other,
              "monthly_gap_before_portfolio_cents_real": max(0, target-other),
              "assumptions": {"monthly_saving_cents": monthly_saving, "annual_return_bps": ret,
                              "annual_inflation_bps": inflation},
              "warning": "Illustrative accumulation only. No taxes, fees, market sequence risk, healthcare changes, debt, or validated pension/Social Security estimate. No retirement sufficiency conclusion."}
    rate = data.get("planning_withdrawal_bps")
    if rate is not None:
        rate = integer(rate, "planning_withdrawal_bps", 1, 1000)
        result["illustrative_monthly_portfolio_draw_cents_real"] = round(real_portfolio*rate/10000/12)
        result["assumptions"]["planning_withdrawal_bps"] = rate
        result["warning"] += " User-supplied withdrawal rate is an assumption, not a safe rate recommendation."
    return result


def paper_open(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    balance = integer(data.get("starting_cash_cents"), "starting_cash_cents", 1)
    existing = db.execute("SELECT 1 FROM paper_accounts WHERE user_id=?", (user,)).fetchone()
    if existing:
        raise ValueError("paper account already exists; reset is not supported")
    db.execute("INSERT INTO paper_accounts VALUES (?,?,0)", (user, balance))
    return {"cash_cents": balance, "paper_only": True}


def symbol(value):
    value = string(value, "symbol", 12).upper()
    if not value.replace(".", "").isalnum() or not value[0].isalpha():
        raise ValueError("invalid symbol")
    return value


def paper_order(db, user, data, task_id):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    sym = symbol(data.get("symbol"))
    side = data.get("side")
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    quantity = integer(data.get("quantity"), "quantity", 1, 1000000)
    price = integer(data.get("price_cents"), "price_cents", 1)
    fee = integer(data.get("fee_cents", 0), "fee_cents", 0, 10**12)
    account = db.execute("SELECT cash_cents,realized_pnl_cents FROM paper_accounts WHERE user_id=?", (user,)).fetchone()
    if not account:
        raise ValueError("open a paper account first")
    position = db.execute("SELECT quantity,cost_cents FROM paper_positions WHERE user_id=? AND symbol=?", (user, sym)).fetchone()
    cash, realized = account
    if side == "buy":
        cost = quantity*price + fee
        if cost > cash:
            raise ValueError("insufficient paper cash")
        new_quantity = quantity + (position[0] if position else 0)
        new_cost = cost + (position[1] if position else 0)
        cash -= cost
    else:
        if not position or quantity > position[0]:
            raise ValueError("insufficient paper shares")
        cost_basis = round(position[1] * quantity / position[0]) if quantity != position[0] else position[1]
        proceeds = quantity*price - fee
        if proceeds < 0:
            raise ValueError("fee exceeds proceeds")
        cash += proceeds
        realized += proceeds - cost_basis
        new_quantity = position[0] - quantity
        new_cost = position[1] - cost_basis
    db.execute("UPDATE paper_accounts SET cash_cents=?,realized_pnl_cents=? WHERE user_id=?", (cash, realized, user))
    if new_quantity:
        db.execute("INSERT INTO paper_positions VALUES (?,?,?,?,?) ON CONFLICT(user_id,symbol) DO UPDATE SET quantity=excluded.quantity,cost_cents=excluded.cost_cents,last_price_cents=excluded.last_price_cents", (user, sym, new_quantity, new_cost, price))
    else:
        db.execute("DELETE FROM paper_positions WHERE user_id=? AND symbol=?", (user, sym))
    db.execute("INSERT INTO paper_orders VALUES (?,?,?,?,?,?,?)", (user, task_id, sym, side, quantity, price, fee))
    return {"paper_only": True, "symbol": sym, "side": side, "quantity": quantity,
            "assumed_fill_price_cents": price, "cash_cents": cash, "realized_pnl_cents": realized,
            "warning": "Simulated immediate fill at a manually supplied price; excludes slippage, spreads, taxes and market restrictions."}


def paper_portfolio(db, user, data):
    account = db.execute("SELECT cash_cents,realized_pnl_cents FROM paper_accounts WHERE user_id=?", (user,)).fetchone()
    if not account:
        raise ValueError("open a paper account first")
    positions = [{"symbol": sym, "quantity": qty, "cost_cents": cost,
                  "last_manual_price_cents": price, "stale_value_cents": qty*price} for sym, qty, cost, price in db.execute(
                      "SELECT symbol,quantity,cost_cents,last_price_cents FROM paper_positions WHERE user_id=? ORDER BY symbol", (user,))]
    return {"paper_only": True, "cash_cents": account[0], "realized_pnl_cents": account[1],
            "positions": positions, "stale_total_value_cents": account[0]+sum(p["stale_value_cents"] for p in positions),
            "warning": "Prices are manually supplied order prices, not live market quotes. Portfolio value may be stale."}
