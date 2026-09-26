# Scope and staged rollout

## Phase 1 — local baseline (included here)

Manual analysis of entered balances, debts, normalized recurring and seasonal cash flow, goals, net worth and scenario trajectories. Reviewed normalized CSV transactions, spending categories, budgets, loan payoff analysis, manual offer comparisons, tax item organization and a manually priced paper portfolio. Evidence-linked recommendations and explicit missing-data warnings. No brokerage, bank, tax authority, lender, or external account access.

## Phase 2 — complete financial picture

Add statement ingestion with user review, duplicate detection, transaction categorization, irregular income and seasonal expenses, debt payment schedules, insurance coverage, emergency reserves, retirement account types, employer benefits, taxes, dependents, household boundaries, and financial milestones. Link source documents to every number, including its date and confidence. Keep other household members' records separately permissioned.

Trajectory engine should eventually model after-tax cash flow, investment contributions, debt amortization, inflation, fees, Social Security/pension estimates where applicable, home value assumptions, retirement withdrawals and stress tests. Distinguish nominal dollars from today's dollars and show sensitivity ranges. The user must be able to change assumptions and see what changed in the recommendation.

## Phase 3 — optional read-only integrations

Connect institutions only with user approval, scoped read-only tokens and revocation. Reconcile imported records with existing data. Never ask Pocket to retain banking passwords in chat. Implement refresh errors, consent tracking and stale-data warnings.

## Phase 4 — trading research and paper execution

Build separately versioned market-data, research, backtest and automated paper-execution modules around the current manual simulation. Account for splits/dividends, data leakage, fees, spread/slippage, taxes, position sizing, strategy drift and strategy failure. Paper performance is not proof of live performance.

## Phase 5 — possible live trading, separate authorization

Only after explicit choice of brokerage and account, legal/compliance review for the intended use, verified strategy and monitored paper performance. Isolate live broker credentials from the chat model and Foreman; hard-code limits outside the model, use a kill switch, and require per-order approval initially. No live-trade route exists in this package. If intended for other users or as a commercial advisory service, evaluate registration, fiduciary duties and disclosures with qualified counsel before deployment.
