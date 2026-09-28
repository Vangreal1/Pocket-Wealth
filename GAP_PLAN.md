# Path to the intended full product

## 1. Reliable financial feed

Add institution-specific statement import adapters and user review, then consent-based read-only account connections. Plaid's Transactions Sync supports cursor-based incremental updates; its product documentation also lists investments and liabilities for holdings/loan data. Build connector interfaces so users can stay manual or replace a provider. Track permission scope, refresh time, account identity, corrections, removals and deduplication. Store access tokens outside the LLM and encrypt private data and backups.

References for one possible U.S. market provider: https://plaid.com/docs/api/products/transactions/ and https://plaid.com/docs/ . Choose connector providers per user's country and institution, including their consent and data residency terms.

## 2. Taxes that can support decisions

Add jurisdiction-specific tax document extraction and a versioned rule engine scoped to tax year, country, region, filing status and the user's circumstances. Build tests against each jurisdiction's authoritative instructions. Keep tax-law updates dated and reviewed. For U.S. users, the IRS Tax Withholding Estimator is a possible early companion workflow. Do not infer tax liability from the present tax organizer.

Reference for U.S. users: https://www.irs.gov/individuals/tax-withholding-estimator . Each jurisdiction requires its own sources and validation.

## 3. Loan lookups and verified comparisons

Choose supported loan types (auto, personal, mortgage, student). Obtain date-stamped public rate data and actual lender quotes through allowed sources; record eligibility assumptions, interest rate versus APR, fees, term and prepayment rules. Public advertised rates are not personalized offers. For mortgages, compare lender Loan Estimates of the same loan type using the official CFPB guidance. Feed verified offers into the existing comparison engine; extend its model for variable rates, points and refinance break-even.

Reference for U.S. mortgages: https://www.consumerfinance.gov/owning-a-home/compare/compare-loan-estimates/ . Other markets require local consumer-credit sources.

## 4. Trading research and controlled execution

Wire `market_research_request` into Foreman's existing internet tool for on-demand questions. Choose source adapters by asset class: official filings for company fundamentals, economic data sources for macro series, central-bank reference data for currencies, and licensed quote providers for tradeable prices. Scraping public pages can answer many one-off questions, but their page structure, terms, delay and coverage vary. The source connector must pass provenance and observation time through `record_market_observation`, and it must never pass a page quote as a broker execution price.

For sustained market observation, add a market data adapter with timestamps, survivorship/corporate-action treatment and licensing, then reproducible backtesting with realistic fees/slippage/taxes. Run candidate strategies only in a paper environment for a monitored period. Alpaca documents a paper environment and separate paper/live credentials, but provider choice and account eligibility are still open. Any live adapter needs isolated credentials, hard risk limits outside the model, kill switch, per-order confirmation at first, reconciliation and failure handling. Commercial advice or trading for others requires legal review before release.

For a user-pinned home-screen quote, implement the Pocket-origin WebSocket bridge described in `ui/QUOTE_WIDGET.md`. A continuous licensed feed is needed; an on-demand website scrape is not a sustained real-time stream. Mount the same responsive component in the desktop window and phone home widget grid.

References: https://www.sec.gov/about/developer-resources , https://fred.stlouisfed.org/docs/api/fred/ , https://data.ecb.europa.eu/help/api/data . For one possible broker: https://docs.alpaca.markets/us/docs/paper-trading and https://docs.alpaca.markets/us/docs/authentication . Broker availability and trading rules vary by market.

## 5. Pocket deployment and acceptance gates

Map the task contract to live Foreman; run Wealth separately under systemd; implement Pocket Functions → Wealth screens. Wire the included export/erase functions to authenticated, explicitly confirmed UI controls; build household permission rules and audit visibility. Encrypted storage is done (AES-256 via SQLCipher, 2026-09-28 - see README.md); backup retention and tested restore in an integration environment are still outstanding. Acceptance checks: bank reconciles with statements; seasonal cash matches known pay cycles; taxes match validated examples; rate quotes have current sources; paper orders cannot reach live API; cross-user access is denied; kill switch is tested before any live trading.

These phases are not all a Claude "wiring" task. Account providers, currencies with different minor-unit scales, currency conversion, tax jurisdictions, lender sources, broker choice, legal model and user approvals require separate product decisions and access. Start with one installed user's accounts; support multiple users only when identity, roles and account access controls are audited.
