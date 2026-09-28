# Pocket-Wealth

Standalone, local-first financial analysis service intended to sit behind Pocket → Foreman. This package is **not integrated** into Pocket or Foreman and has **no trading execution code**.

## Current capabilities

- Local SQLite storage for user-entered accounts, balances, recurring monthly income and expenses, liabilities, goals, monthly seasonal plans, budgets and tax-year items. Each user sets a currency, time zone and tax jurisdiction before adding money records.
- Reviewed CSV or manual transaction batches with deduplication, monthly spending by category, transfer exclusion, and category budget comparisons. The import format is normalized; bank-specific statement formats need adapters.
- Loan payoff analysis with extra-payment scenarios and comparison of manually entered fixed-rate offers. There is no live lender search.
- Multi-debt avalanche and snowball payoff comparisons, spending trends, and an illustrative retirement accumulation scenario.
- Tax-year organizer that totals entered wages, unemployment, investment items, withholding and potential deductions. It does not compute tax owed, classify deductibility or file a return.
- Isolated paper portfolio with manually supplied prices, cash and position checks, simulated buys/sells, and a realized profit/loss ledger. No market data feed, strategy engine, or live order path.
- On-demand market research contract: Foreman can use its internet tools for an individual question, then a trusted source connector can submit a timestamped, cited observation. Wealth shows source and age; it does not fetch arbitrary websites or claim a stored quote is current.
- Example questions for the Foreman web adapter: "What is the current gold price?" and "Show me the S&P 500 overall." The response should show the source website link, its quote/index time, and whether data is delayed.
- User-scoped home-screen quote pins and a responsive Web Component prototype for desktop windows and phone widgets. A continuously updating feed requires a Pocket-side WebSocket bridge and a licensed provider.
- Per-user isolation keyed by `user_id`; caller identity is asserted by the trusted Foreman service, not by the end-user payload.
- Wealth trajectory: net worth today; monthly surplus; cash runway; 1/5/10-year net-worth scenarios; projected goal context. Missing account, income, or expense data withholds projections. Scenarios are illustrative, not market predictions.
- Monthly surplus accrues as cash by default. Only the amount explicitly specified as a monthly investment is modeled as earning an investment return.
- A complete 12-month income/expense profile replaces flat monthly entries for the projection, allowing any seasonal pay or spending pattern. A 12-month cash outlook flags cash shortfalls hidden by annual averages.
- Evidence-linked advice rules: cash buffer, negative cash flow, high-rate debt, missing data and goal gaps. Each recommendation explains inputs and limitations.
- Loopback-only HTTP service with bearer-token authentication, request limits, replay-safe task IDs, an audit log, and no broker connection or outbound network calls.
- Versioned transactional migration from prior unversioned databases, user-data JSON export, and explicitly confirmed per-user active-record erasure.

## Run locally

Requires Python 3.11+ and `sqlcipher3-binary` (see requirements.txt) - the database is
encrypted at rest (AES-256 via SQLCipher, added 2026-09-28), which is the one third-party
dependency this service has. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
if you don't already have a venv here.

```bash
export WEALTH_TOKEN='replace-with-a-long-random-secret'
export WEALTH_DB='/path/to/private/wealth.sqlite3'
export WEALTH_DB_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
.venv/bin/python3 -m wealth.service
```

`WEALTH_DB_KEY` must be exactly 64 hex characters (a raw 256-bit key, not a human passphrase -
generate it once and keep it with your other secrets; losing it means losing access to the
database, same as losing any other encryption key). A brand-new `WEALTH_DB` is created encrypted
from the start; migrating an existing plaintext database needs SQLCipher's own
`ATTACH ... KEY ...; SELECT sqlcipher_export(...)` pattern first (see wealth/service.py's
`_connect()` for the exact key format it expects).

Default bind is `127.0.0.1:8788`. Authenticated `GET /health` and `GET /capabilities` support service checks and Foreman discovery. Optional, separate 32+ character secrets gate sensitive operations: `WEALTH_SOURCE_TOKEN` for sourced market ingestion (`X-Wealth-Source-Token`), `WEALTH_APPROVAL_TOKEN` for saving reviewed transactions (`X-Wealth-Approval-Token`), and `WEALTH_DATA_TOKEN` for export/erasure (`X-Wealth-Data-Token`). Without a corresponding token, that HTTP action is disabled. These secrets must be distinct from `WEALTH_TOKEN` and must never be passed through model-generated text. Do not expose the service to a network or reuse Pocket's user-facing authentication. Keep tokens (including `WEALTH_DB_KEY`) in a protected systemd environment file, not in source control. The database itself is encrypted at rest; backups and exports (`export_user_data`) are not encrypted by this service and should be protected separately.

Example request:

```bash
curl -H "Authorization: Bearer $WEALTH_TOKEN" -H 'Content-Type: application/json' \
  -d '{"task_id":"profile-demo-1","user_id":"demo-user","action":"upsert_profile","data":{"currency":"USD","timezone":"America/New_York","tax_jurisdiction":"US-NY"}}' \
  http://127.0.0.1:8788/tasks
```

Submit data with the actions in `CONTRACT.md`. `CAPABILITIES.md` maps the working features; `GAP_PLAN.md` details the path to the wider product. `ui/QUOTE_WIDGET.md` describes the desktop/phone component and stream contract. Only a trusted local caller should assign `user_id`. Use `python3 -m unittest discover -s tests -v` to run tests.

## Importing a bank statement

`import_csv` accepts a raw CSV export from any bank via an optional `mapping` - the bank's own
column names, date format, and amount convention never need to match Wealth's internal schema
(added 2026-09-28, see `wealth/features.py`'s `map_bank_csv`). Without `mapping`, the CSV must
already use Wealth's own headers (`posted_on,amount_cents,direction,category,description,account_id`).

A mapped import still goes through the exact same `dry_run`/`approved` review and duplicate
detection as any other import - it's only a format conversion, not a separate save path.

Required in every `mapping`: `posted_on` (the date column name), `description` (the description
column name), `amount_mode`, and either `account_id` (a literal, used for every row - the normal
case for a single-account statement) or `account_id_column` (pulls it per-row, for a combined
multi-account export). `category` is optional (falls back to `"uncategorized"`); `date_format`
is optional (a `datetime.strptime` format string; omit it if the bank's dates are already ISO
`YYYY-MM-DD`). Amounts tolerate `$`, thousands separators, and parenthesized negatives.

`amount_mode` is one of:
- **`signed`** - one amount column, sign indicates direction. Needs `amount_column`. Negative
  means expense by default; set `negative_means: "income"` if a bank does it backwards.
- **`debit_credit`** - two separate columns. Needs `debit_column` and `credit_column`; exactly
  one must have a value per row.
- **`unsigned_with_type`** - one always-positive amount column plus a separate type column.
  Needs `amount_column`, `type_column`, `expense_values`, and `income_values` (lists of the
  type column's own values, matched case-insensitively).

Example - a typical single-amount-column bank export:

```json
{"csv_text": "Date,Amount,Description\n01/20/2026,-15.75,Coffee Shop\n01/21/2026,2000.00,Paycheck\n",
 "mapping": {"posted_on": "Date", "date_format": "%m/%d/%Y", "description": "Description",
             "account_id": "checking", "amount_mode": "signed", "amount_column": "Amount"},
 "dry_run": true}
```

## Handoff / production gaps

Claude Code should map `CONTRACT.md` to Foreman's actual task model, register the service, configure systemd and Pocket's Functions UI, and add authentication/authorization appropriate to the live stack. The database itself is encrypted at rest now (AES-256 via SQLCipher); still outstanding before handling real financial records at scale: backup restore tests, retention rules for backups/exports (which are not themselves encrypted by this service), and bank-specific statement adapters with user review. The `approved` flag and its separate gateway credential must originate from a Pocket confirmation flow, not from model-generated text. The gateway credentials do not prove which user initiated the request; Foreman must bind `user_id` to Pocket's authenticated session. No API credentials, bank connections, payment movement, live trading, or automatic investment decisions are included.

Trading roadmap: read-only market data → reproducible backtests → automated strategies within the paper environment → separately reviewed live-trading adapter with per-order confirmation, independent hard limits and kill switch. The current paper portfolio accepts simulated manually priced orders only. Never treat the language model's generated text as executable broker instructions.
