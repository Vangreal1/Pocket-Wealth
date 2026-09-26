# Pocket-Wealth integration handoff for Claude Code

Pocket-Wealth is a standalone Python service. The ZIP is the canonical standalone source. Do not merge its internals into Pocket's main process. Current tests: `python3 -m unittest discover -s tests -v`.

Read `CAPABILITIES.md` for exact current functionality and `GAP_PLAN.md` for the staged product work. Do not describe roadmap entries as implemented.

## What works

| Capability | Current scope |
| --- | --- |
| Financial snapshot | Manual balances, debts, recurring monthly cash flow, goals, net worth and scenario assumptions |
| Spending | Reviewed normalized CSV/manual transaction batches, deduplication, transfers excluded, categories, monthly budgets and trends |
| Income planning | Complete 12-month profile for seasonal income and expenses; trajectory uses actual month order and a 12-month cash shortfall check |
| Loans | Fixed-rate payoff and extra-payment comparison, avalanche/snowball plan; manually entered quote comparison |
| Taxes | User-entered tax-year totals organized by category; no liability estimate or filing |
| Advisor | Rule-based cash buffer, recurring shortfall, high-rate debt and missing-data flags with evidence fields; qualified five-year direction assessment |
| Retirement | User-supplied age, contributions and targets modeled against existing investment balance; no sufficiency conclusion |
| Trading lab | Manually priced paper portfolio and simulated orders; no market feed or automatic strategies |
| Market questions | Research request and sourced-observation storage contract; actual web retrieval remains a Foreman integration task |
| Quote widgets | User-scoped pins plus a responsive Web Component for desktop and phone; Pocket stream and placement remain integration work |

## Integration work

1. Verify the live Foreman task contract and implement its adapter to `POST /tasks`, using Foreman's authenticated user identity as `user_id`. For every new request, generate a new task ID. Preserve task ID on retries.
2. Register the separate service in systemd, bound to loopback only. Use a protected environment file for token and database path. Configure filesystem permissions, encrypted storage and backups. Do not add secrets to Git.
3. Expose Pocket Functions → Wealth with an onboarding step for currency, time zone and tax jurisdiction, then Overview, Spending, Income, Debts, Taxes, Paper Lab and Data screens. Amounts use hundredths for supported two-decimal currencies; display currency and date. Surface incomplete or stale data and scenario assumptions prominently.
4. Build an explicit statement preview and confirmation flow. Only that trusted flow may set `dry_run:false, approved:true` and the separate approval header; never infer either from an LLM message. Show duplicates and category corrections before save.
5. Add personal authorization and household role rules. A user must not be able to change the `user_id` in a submitted task. Distinguish one's own finances from a family member's data.
6. Wire the included per-user export/erase actions to authenticated Pocket UI confirmation, keeping the privileged data header outside the model. Establish backup retention and secure download handling; test restores, bank-specific import adapters and statement reconciliation before ingesting real records. Transactional migration and lifecycle tests are included in the ZIP.
7. Route Wealth's `market_research_request` to a Foreman web task, including commodity queries such as gold and index overviews such as S&P 500. Restrict `record_market_observation` to a separate trusted connector credential. Have Pocket show a clickable source website link, observation time, retrieval time, and the limits of scraped data.
8. Read `ui/QUOTE_WIDGET.md`, mount the Web Component on Pocket home screens, and implement the same-origin WebSocket feed bridge. Do not put provider credentials in the browser. Show delayed/stale/closed states based on the feed's actual entitlements and trading session.

## External integrations still required for the broader product

Read-only institution sync; live lender rate research with dated sources and eligibility caveats; maintained tax-law rules or qualified tax software integration; market data; historical backtests; automated paper strategies; broker adapter with separate live-trading authorization, hard limits and kill switch. These are **not** in the ZIP. Do not enable live trading through the Foreman task contract.

## Model and data caveats

Scenario values are illustrative today's dollars. Debts and property stay constant; recurring contributions are held constant; tax effects, inflation changes, fees, market shocks and spending changes are not forecast. Current source labels are manual only. "Advisor" here means explainable software prompts, not a regulated fiduciary service. If Pocket-Wealth is offered to others commercially, get a legal review of advice and trading activity before enabling it.
