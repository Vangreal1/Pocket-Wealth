"""Local financial records, deterministic trajectory and explainable rules."""
import json
import hashlib
import sqlite3
from datetime import date, datetime, timezone
from . import features, profile, market, widgets, data_admin

KINDS = {"cash", "investment", "property", "other_asset", "debt"}
SCHEMA_VERSION = 1


def initialize(db):
    db.execute("PRAGMA foreign_keys=ON")
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise ValueError("database schema is newer than this Pocket-Wealth build")
    if version == SCHEMA_VERSION:
        return
    # v0 was the unversioned prototype. Each DDL statement runs inside one
    # transaction; executescript would commit before a failure could roll back.
    ddl = """
      CREATE TABLE IF NOT EXISTS accounts (
        user_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL,
        kind TEXT NOT NULL, balance_cents INTEGER NOT NULL, apr_bps INTEGER NOT NULL,
        as_of TEXT NOT NULL, source TEXT NOT NULL, PRIMARY KEY(user_id,id));
      CREATE TABLE IF NOT EXISTS cashflows (
        user_id TEXT NOT NULL, id TEXT NOT NULL, label TEXT NOT NULL,
        kind TEXT NOT NULL, monthly_cents INTEGER NOT NULL, source TEXT NOT NULL,
        PRIMARY KEY(user_id,id));
      CREATE TABLE IF NOT EXISTS goals (
        user_id TEXT NOT NULL, id TEXT NOT NULL, label TEXT NOT NULL,
        target_cents INTEGER NOT NULL, target_year INTEGER NOT NULL,
        PRIMARY KEY(user_id,id));
      CREATE TABLE IF NOT EXISTS tasks (
        user_id TEXT NOT NULL, task_id TEXT NOT NULL, response TEXT NOT NULL,
        request_hash TEXT,
        PRIMARY KEY(user_id,task_id));
      CREATE TABLE IF NOT EXISTS audit (
        at TEXT NOT NULL, user_id TEXT NOT NULL, task_id TEXT NOT NULL,
        action TEXT NOT NULL, outcome TEXT NOT NULL);
    """
    try:
        db.execute("BEGIN IMMEDIATE")
        for statement in ddl.split(";"):
            if statement.strip():
                db.execute(statement)
        columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
        if "request_hash" not in columns:
            db.execute("ALTER TABLE tasks ADD COLUMN request_hash TEXT")
        features.ensure_tables(db)
        profile.ensure_table(db)
        market.ensure_table(db)
        widgets.ensure_table(db)
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        db.commit()
    except Exception:
        db.rollback()
        raise


def integer(value, label, minimum=0, maximum=10**15):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer in [{minimum}, {maximum}]")
    return value


def string(value, label, limit=100):
    if not isinstance(value, str) or not 1 <= len(value) <= limit or not value.strip():
        raise ValueError(f"{label} must be a nonempty string of at most {limit} characters")
    return value.strip()


def put(db, user, action, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    item_id = string(data.get("id"), "id")
    source = data.get("source", "manual")
    if source != "manual":
        raise ValueError("only manual source is supported in this release")
    if action == "upsert_account":
        kind = data.get("kind")
        if kind not in KINDS:
            raise ValueError("invalid account kind")
        as_of = string(data.get("as_of"), "as_of", 10)
        try:
            date.fromisoformat(as_of)
        except ValueError as exc:
            raise ValueError("as_of must be an ISO date") from exc
        if as_of > profile.local_today(db, user).isoformat():
            raise ValueError("as_of cannot be in the future")
        values = (user, item_id, string(data.get("name"), "name"), kind,
                  integer(data.get("balance_cents"), "balance_cents"),
                  integer(data.get("apr_bps", 0), "apr_bps", 0, 100000), as_of, source)
        db.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(user_id,id) DO UPDATE SET name=excluded.name,kind=excluded.kind,balance_cents=excluded.balance_cents,apr_bps=excluded.apr_bps,as_of=excluded.as_of,source=excluded.source", values)
    elif action == "upsert_cashflow":
        kind = data.get("kind")
        if kind not in {"income", "expense"}:
            raise ValueError("invalid cashflow kind")
        values = (user, item_id, string(data.get("label"), "label"), kind,
                  integer(data.get("monthly_cents"), "monthly_cents"), source)
        db.execute("INSERT INTO cashflows VALUES (?,?,?,?,?,?) ON CONFLICT(user_id,id) DO UPDATE SET label=excluded.label,kind=excluded.kind,monthly_cents=excluded.monthly_cents,source=excluded.source", values)
    else:
        values = (user, item_id, string(data.get("label"), "label"),
                  integer(data.get("target_cents"), "target_cents"),
                  integer(data.get("target_year"), "target_year", profile.local_today(db, user).year, profile.local_today(db, user).year+80))
        db.execute("INSERT INTO goals VALUES (?,?,?,?,?) ON CONFLICT(user_id,id) DO UPDATE SET label=excluded.label,target_cents=excluded.target_cents,target_year=excluded.target_year", values)
    return {"id": item_id, "saved": True}


def overview(db, user, assumptions=None):
    assumptions = assumptions or {}
    if not isinstance(assumptions, dict):
        raise ValueError("assumptions must be an object")
    today = profile.local_today(db, user)
    settings = profile.get(db, user)
    ret = integer(assumptions.get("annual_return_bps", 300), "annual_return_bps", -10000, 20000)
    inflation = integer(assumptions.get("annual_inflation_bps", 250), "annual_inflation_bps", 0, 10000)
    monthly_investment = integer(assumptions.get("monthly_investment_cents", 0), "monthly_investment_cents")
    years = assumptions.get("years", [1, 5, 10])
    if not isinstance(years, list) or not 1 <= len(years) <= 10:
        raise ValueError("years must be a list of 1–10 horizons")
    years = sorted(set(integer(y, "year horizon", 1, 50) for y in years))
    accounts = [dict(zip(("id", "name", "kind", "balance_cents", "apr_bps", "as_of", "source"), row)) for row in db.execute("SELECT id,name,kind,balance_cents,apr_bps,as_of,source FROM accounts WHERE user_id=?", (user,))]
    flows = [dict(zip(("id", "label", "kind", "monthly_cents", "source"), row)) for row in db.execute("SELECT id,label,kind,monthly_cents,source FROM cashflows WHERE user_id=?", (user,))]
    goals = [dict(zip(("id", "label", "target_cents", "target_year"), row)) for row in db.execute("SELECT id,label,target_cents,target_year FROM goals WHERE user_id=?", (user,))]
    seasonal = features.seasonal_profile(db, user)
    seasonal_ready = len(seasonal) == 12
    assets = sum(a["balance_cents"] for a in accounts if a["kind"] != "debt")
    debts = sum(a["balance_cents"] for a in accounts if a["kind"] == "debt")
    liquid = sum(a["balance_cents"] for a in accounts if a["kind"] == "cash")
    income = sum(f["monthly_cents"] for f in flows if f["kind"] == "income")
    expense = sum(f["monthly_cents"] for f in flows if f["kind"] == "expense")
    if seasonal_ready:
        income = round(sum(v[0] for v in seasonal.values()) / 12)
        expense = round(sum(v[1] for v in seasonal.values()) / 12)
    surplus = income - expense
    networth = assets - debts
    has_income = (seasonal_ready and any(v[0] for v in seasonal.values())) or any(f["kind"] == "income" for f in flows)
    has_expenses = (seasonal_ready and any(v[1] for v in seasonal.values())) or any(f["kind"] == "expense" for f in flows)
    can_project = bool(settings) and bool(accounts) and has_income and has_expenses
    if can_project and monthly_investment > (max(0, *(i-e for i, e in seasonal.values())) if seasonal_ready else max(0, surplus)):
        raise ValueError("monthly_investment_cents cannot exceed entered monthly surplus")
    # Only invested assets earn modeled return. The remaining surplus accumulates
    # as cash; negative surplus draws down cash. Debt balances stay constant.
    invested = sum(a["balance_cents"] for a in accounts if a["kind"] == "investment")
    noninvested_net = networth - invested
    def project(y, rate_bps):
        monthly_rate = (1 + rate_bps / 10000) ** (1 / 12) - 1
        projected = invested
        cash_change = 0
        for offset in range(y * 12):
            monthly_surplus = (seasonal[(today.month - 1 + offset) % 12 + 1][0]
                               - seasonal[(today.month - 1 + offset) % 12 + 1][1]) if seasonal_ready else surplus
            contribution = min(monthly_investment, max(0, monthly_surplus))
            projected = projected * (1 + monthly_rate) + contribution
            cash_change += monthly_surplus - contribution
        nominal = noninvested_net + projected + cash_change
        return round(nominal / ((1 + inflation / 10000) ** y))
    low_rate = min(-200, ret - 500)
    high_rate = max(600, ret + 500)
    scenarios = ([{"years": y, "lower_cents_real": project(y, low_rate),
                   "base_cents_real": project(y, ret), "higher_cents_real": project(y, high_rate)} for y in years]
                 if can_project else [])
    next_12_months = []
    if can_project:
        running_cash = liquid
        for offset in range(12):
            month_index = today.month - 1 + offset
            month = month_index % 12 + 1
            year = today.year + month_index // 12
            inc, out = seasonal[month] if seasonal_ready else (income, expense)
            contribution = min(monthly_investment, max(0, inc-out))
            running_cash += inc-out-contribution
            next_12_months.append({"month": f"{year:04d}-{month:02d}", "income_cents": inc,
                                   "expenses_cents": out, "invested_cents": contribution,
                                   "estimated_end_cash_cents": running_cash})
    warnings = []
    if not accounts:
        warnings.append("No accounts entered; net worth is incomplete.")
    if not settings:
        warnings.append("Set user currency and timezone before entering financial data or projecting trajectory.")
    if not has_income or not has_expenses:
        warnings.append("Income or expense data is incomplete; trajectory is withheld.")
    if seasonal and not seasonal_ready:
        warnings.append("Seasonal profile needs all 12 months; recurring monthly entries are used until it is complete.")
    stale_ids = [a["id"] for a in accounts if (today - date.fromisoformat(a["as_of"])).days > 90]
    if stale_ids:
        warnings.append("At least one balance is over 90 days old.")
    warnings.append("Projections are illustrative, not predictions; they omit taxes, debt amortization, property changes, and irregular cash flows. Cash withdrawals are not bounded at zero.")
    recommendations = []
    def recommend(priority, title, reason, evidence):
        recommendations.append({"priority": priority, "title": title, "reason": reason, "evidence": evidence})
    if not can_project:
        recommend("first", "Complete your financial snapshot", "Add account balances and recurring income and expenses before relying on trajectory advice.", {"accounts": len(accounts), "has_income": has_income, "has_expenses": has_expenses})
    if can_project and surplus < 0:
        recommend("high", "Investigate a recurring shortfall", "Entered recurring expenses exceed entered income; verify completeness before deciding what to change.", {"monthly_surplus_cents": surplus})
    if next_12_months and any(item["estimated_end_cash_cents"] < 0 for item in next_12_months):
        first_shortfall = next(item for item in next_12_months if item["estimated_end_cash_cents"] < 0)
        recommend("high", "Plan for a projected cash shortfall", "Entered seasonal income, expenses, planned investing, and starting cash imply a negative cash balance. Check timing, irregular expenses and available reserves.", {"first_shortfall_month": first_shortfall["month"], "estimated_end_cash_cents": first_shortfall["estimated_end_cash_cents"]})
    if can_project and expense > 0 and liquid < expense * 3:
        recommend("review", "Review your cash buffer", "Entered liquid cash is below three months of entered expenses; choose a target based on income stability and obligations.", {"cash_cents": liquid, "monthly_expenses_cents": expense, "months": round(liquid / expense, 2)})
    high_rate_debts = [a for a in accounts if a["kind"] == "debt" and a["apr_bps"] >= 1000 and a["balance_cents"] > 0]
    if high_rate_debts:
        recommend("review", "Review high-rate debt", "Compare debt payoff with investing after checking terms, liquidity and tax effects.", {"debts": [{"id": a["id"], "apr_bps": a["apr_bps"], "balance_cents": a["balance_cents"]} for a in high_rate_debts]})
    goal_progress = []
    for g in goals:
        horizon = max(1, g["target_year"] - today.year)
        projected = project(horizon, ret) if can_project else None
        goal_progress.append({"id": g["id"], "label": g["label"], "target_year": g["target_year"], "target_cents": g["target_cents"], "projected_networth_cents_real": projected, "comparable": False})
    if goals:
        warnings.append("Goal targets and projected net worth are not directly comparable until goal scope, inflation basis and earmarked assets are specified.")
    if can_project:
        five_years = project(5, ret)
        direction = ("improving_under_assumptions" if five_years > networth else
                     "declining_under_assumptions" if five_years < networth else "flat_under_assumptions")
        assessment = {"direction": direction, "confidence": "limited",
                      "current_net_worth_cents": networth,
                      "five_year_net_worth_cents_real": five_years,
                      "annual_recurring_surplus_cents": (sum(v[0]-v[1] for v in seasonal.values())
                                                          if seasonal_ready else surplus*12),
                      "near_term_cash_shortfall": any(m["estimated_end_cash_cents"] < 0 for m in next_12_months),
                      "reason": "Direction compares entered net worth with a five-year projection using the displayed assumptions; it does not establish progress toward a retirement or savings goal."}
    else:
        assessment = {"direction": "unknown", "confidence": "insufficient_data",
                      "reason": "Add assets, income, and expenses before assessing trajectory."}
    return {"as_of": today.isoformat(), "profile": settings,
            "assets_cents": assets, "debt_cents": debts,
            "net_worth_cents": networth, "cash_cents": liquid, "monthly_income_cents": income,
            "monthly_expenses_cents": expense, "monthly_surplus_cents": surplus,
            "monthly_values_are_annual_averages": seasonal_ready,
            "annual_income_cents": sum(v[0] for v in seasonal.values()) if seasonal_ready else income*12,
            "annual_expenses_cents": sum(v[1] for v in seasonal.values()) if seasonal_ready else expense*12,
            "cash_runway_months": round(liquid / expense, 2) if can_project and expense else None,
            "assumptions": {"annual_return_bps": ret, "lower_annual_return_bps": low_rate,
                            "higher_annual_return_bps": high_rate, "annual_inflation_bps": inflation,
                            "monthly_surplus_held_constant": True, "monthly_investment_cents": monthly_investment},
            "trajectory_status": "available" if can_project else "insufficient_data",
            "data_quality": {"has_accounts": bool(accounts), "has_income": has_income,
                             "has_expenses": has_expenses, "stale_account_ids": stale_ids,
                             "account_count": len(accounts), "cashflow_count": len(flows),
                             "seasonal_months": len(seasonal)},
            "trajectory": scenarios, "trajectory_assessment": assessment,
            "next_12_months": next_12_months,
            "goals": goal_progress, "recommendations": recommendations,
            "data_sources": {"accounts": [{"id": a["id"], "as_of": a["as_of"], "source": a["source"]} for a in accounts], "cashflows": [{"id": f["id"], "source": f["source"]} for f in flows]},
            "warnings": warnings}


def execute(db, payload):
    if not isinstance(payload, dict):
        raise ValueError("request must be an object")
    user = string(payload.get("user_id"), "user_id")
    task_id = string(payload.get("task_id"), "task_id")
    action = payload.get("action")
    feature_actions = {"add_transactions", "import_csv", "spending_report", "upsert_budget", "upsert_seasonal",
                       "spending_trends", "upsert_loan_terms", "loan_analysis", "debt_plan", "compare_loan_quotes",
                       "upsert_tax_item", "tax_organizer", "retirement_scenario",
                       "paper_open", "paper_order", "paper_portfolio"}
    market_actions = {"market_research_request", "record_market_observation", "market_snapshot"}
    widget_actions = {"pin_quote_widget", "list_quote_widgets", "unpin_quote_widget"}
    admin_actions = {"export_user_data", "delete_user_data"}
    if action not in {"overview", "upsert_profile", "upsert_account", "upsert_cashflow", "upsert_goal"} | feature_actions | market_actions | widget_actions | admin_actions:
        raise ValueError("unsupported action")
    mutations = {"upsert_account", "upsert_cashflow", "upsert_goal", "upsert_seasonal", "upsert_budget",
                 "add_transactions", "import_csv", "upsert_loan_terms", "upsert_tax_item", "paper_open", "paper_order"}
    if action in mutations and not profile.get(db, user):
        raise ValueError("set user profile with currency and timezone first")
    request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    with db:
        # Export and erase never cache a full sensitive export in the task table.
        # Erase leaves no per-user task/audit record behind after completion.
        if action in admin_actions:
            result = (data_admin.export_user_data(db, user, payload.get("data"))
                      if action == "export_user_data" else
                      data_admin.delete_user_data(db, user, payload.get("data")))
            return {"task_id": task_id, "status": "completed", "result": result, "warnings": [result["warning"]]}
        previous = db.execute("SELECT response,request_hash FROM tasks WHERE user_id=? AND task_id=?", (user, task_id)).fetchone()
        if previous:
            if previous[1] != request_hash:
                raise ValueError("task_id was already used with a different request")
            return json.loads(previous[0])
        if action == "overview":
            result = overview(db, user, payload.get("assumptions"))
        elif action == "upsert_profile":
            result = profile.upsert_profile(db, user, payload.get("data"))
        elif action in market_actions:
            methods = {"market_research_request": market.research_request,
                       "record_market_observation": market.record_observation,
                       "market_snapshot": market.snapshot}
            result = methods[action](db, user, payload.get("data"))
        elif action in widget_actions:
            methods = {"pin_quote_widget": widgets.pin, "list_quote_widgets": widgets.list_widgets,
                       "unpin_quote_widget": widgets.unpin}
            result = methods[action](db, user, payload.get("data"))
        elif action == "paper_order":
            result = features.paper_order(db, user, payload.get("data"), task_id)
        elif action in feature_actions:
            result = getattr(features, action)(db, user, payload.get("data"))
        else:
            result = put(db, user, action, payload.get("data"))
        response = {"task_id": task_id, "status": "completed", "result": result, "warnings": result.get("warnings", [])}
        db.execute("INSERT INTO tasks(user_id,task_id,response,request_hash) VALUES (?,?,?,?)", (user, task_id, json.dumps(response), request_hash))
        db.execute("INSERT INTO audit VALUES (?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(), user, task_id, action, "completed"))
        return response
