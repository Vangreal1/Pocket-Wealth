# Pocket-Wealth functional map

This is the exact feature boundary of the standalone ZIP. A Pocket/Foreman UI is **not** included.

## Working now

| Area | Implemented functions | Limits |
| --- | --- | --- |
| Core records | Per-user currency, time zone and jurisdiction settings; manual accounts, assets, debts, goals, recurring income/expenses, per-user isolation | No account aggregation or document parser |
| Spending | Preview/confirm normalized CSV or manual transactions, dedup, categories, transfers excluded, monthly budgets and trends | Bank-specific exports need adapters; partial data may distort trends |
| Cash flow | Flat recurring and full 12-month seasonal profile, next 12 months of cash, shortfall alert | Irregular one-offs and tax changes are excluded |
| Overall wealth | Net worth, liquid cash, inflation-adjusted scenarios in the user's currency, five-year direction assessment, evidence-linked advice | Confidence limited; not a promise or goal adequacy test |
| Loans | Fixed APR payoff, extra-payment analysis, debt avalanche and snowball, compare entered fixed-rate offers | No lender lookup, credit check, or personalized quote |
| Retirement | Retirement accumulation scenario with user-entered savings, target and other income; optional user-chosen draw rate | No Social Security/benefit verification or sufficiency verdict |
| Taxes | Organize manually entered tax-year income, withholding and potential deductions | No tax law engine, withholding estimate, filing, or determination of deductibility |
| Trading | Manual-price paper portfolio with simulated buys/sells, cash and position checks, realized P&L | No market data, backtest, automatic strategy or live trades |
| Market research | Generate a user-requested research task and retain time-stamped observations from a trusted Foreman web connector | No built-in scraper, no continuous market monitoring, no verified execution quotes |
| Home quote widgets | Save per-user pins, list/remove them, and render a responsive desktop/phone Web Component with feed/source/freshness states | Pocket home-screen mount and licensed live stream bridge still need integration |
| Operations | Local SQLite, transactional versioned migration, per-user export/erase, loopback HTTP with separate privileged-action tokens, audit entries, replay-safe task IDs and capabilities endpoint | Encryption, backup retention, UI confirmation and authenticated identity binding require Pocket/Foreman integration |

## Important input convention

Every amount uses integer hundredths of the configured two-decimal currency (the v1 field names say `_cents`), rates are basis points, and scenarios use today's purchasing power in that same currency. There is no currency conversion. Zero- and three-decimal currencies, cross-currency portfolios, and jurisdiction-specific tax calculations are future work. The account source is manual only. Missing/stale inputs and simplified assumptions are returned with the analysis. Foreman must derive `user_id` and import approval from authenticated Pocket state rather than chat text.
