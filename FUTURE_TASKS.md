# Future Tasks

## Earnings Options Trading Bot

Status: planned, not started.

Goal: build an earnings options trading bot that reuses modules from this project and helps create and execute option-combination strategies one to two weeks before a company's earnings report.

High-level idea:

- Use an LLM, likely Claude Sonnet 3.6 or a comparable model, to analyze a target stock before earnings.
- Inputs should include news, earnings history and upcoming earnings date, insider transactions, option chain data, price action, volatility, and other relevant market context.
- Generate strategies for multiple scenarios, budgets, and user judgment inputs.
- Support option combinations rather than only single-leg trades.
- Eventually connect to brokerage APIs to place, monitor, adjust, and close trades automatically.

Expected reuse from this project:

- Telegram bot command and notification patterns from `main.py` and `bot/handlers.py`.
- Earnings lookup and cache logic from `bot/earnings.py` and `bot/earnings_cache.py`.
- Database configuration and SQLAlchemy setup from `utils/config.py` and `utils/db.py`.
- Existing Fintel scraping patterns where useful, especially short squeeze and options-flow context.

Initial implementation notes:

- Start with research and strategy generation only; do not enable live trading first.
- Add paper-trading or dry-run execution before any real brokerage integration.
- Require explicit human approval before order placement until the strategy and risk controls are proven.
- Store model inputs, generated thesis, selected strategy, order plan, and final outcome for later review.
- Treat brokerage credentials and account data as secrets, separate from repo code.

Open design questions:

- Which broker API to use for options execution.
- Which LLM provider and model to use in production.
- How to fetch reliable option chain, implied volatility, and Greeks data.
- How to model budgets, max loss, target profit, exit rules, and post-earnings volatility crush.
- What Telegram commands or UI flow should control analysis, approval, and execution.

## Fintel Unusual Trade Copy-Trading Bot

Status: planned, not started.

Goal: use the option block trade data collected by the existing Fintel SOUT module to infer the likely purpose of large unusual trades, then help follow selected trades under a fixed user budget.

High-level idea:

- Use new Fintel SOUT rows as candidate signals.
- Analyze whether a large option trade is likely directional speculation, hedge, spread leg, volatility trade, earnings positioning, closing trade, or noise.
- Combine SOUT fields with option chain context, underlying price action, news, earnings calendar, volume/open-interest changes, bid/ask location, sweep/block characteristics, and recent related trades.
- Score each candidate for confidence, urgency, liquidity, risk/reward, and fit with the user's available budget.
- Generate follow-trade plans such as same contract, cheaper nearby strike, debit spread, calendar spread, or no-trade.
- Eventually support automated or semi-automated execution with strict budget and risk limits.

Expected reuse from this project:

- `scraper_service.py` SOUT scraping, deduplication, alert filtering, and Telegram push flow.
- `FintelSout` storage in `utils/db.py` as the primary signal source.
- Telegram menus and command handlers from `bot/handlers.py` for review, approval, and follow-up tracking.
- Existing earnings cache if the unusual trade is near an earnings event.

Initial implementation notes:

- Start as an analysis-only feature that explains the likely purpose of each large trade.
- Add a paper-trading mode before any real order placement.
- Require explicit user approval before copying any trade.
- Enforce per-trade and daily budget limits.
- Prefer liquid contracts and avoid following trades with wide spreads, stale quotes, or unclear intent.
- Store the original Fintel row, analysis result, proposed trade, user decision, execution result, and later P/L for feedback.

Open design questions:

- How to distinguish opening vs closing trades when Fintel data is incomplete.
- Which market data provider to use for real-time option chain, Greeks, implied volatility, bid/ask, volume, and open interest.
- How to identify multi-leg trades that appear as separate SOUT rows.
- How to size a copied trade under a small budget without changing the risk profile too much.
- Which broker API to use and what approval workflow should be required before live execution.

## Moomoo and IBKR API Integration

Status: planned, not started.

Goal: use moomoo and IBKR APIs together, with IBKR used to supplement market data and broker data that may be missing, delayed, or less reliable from moomoo.

High-level idea:

- Keep moomoo as one primary broker or market-data interface where it is convenient.
- Add IBKR API as a complementary data source for option chains, Greeks, implied volatility, quotes, positions, orders, executions, account data, and historical bars.
- Build a normalized data layer so the rest of the project can request market data without caring whether the source is moomoo, IBKR, or a fallback.
- Compare data from both sources for key fields such as bid/ask, volume, open interest, implied volatility, and contract metadata.
- Prefer IBKR as a validation or backup source before generating or executing option strategies.

Expected reuse from this project:

- Database configuration and SQLAlchemy patterns from `utils/db.py`.
- Telegram command and alert flow from `bot/handlers.py`.
- Future trading bot modules that need option chains, quotes, positions, and order status.
- Existing scraper and Fintel signal modules as upstream signal sources.

Initial implementation notes:

- Start with read-only market data and account data integration.
- Add source labels and timestamps to every normalized quote or contract record.
- Cache slow or rate-limited data where appropriate.
- Keep broker credentials out of git and load them through environment-backed config.
- Add paper-trading or dry-run order routing before any real order placement.

Open design questions:

- Which API should be authoritative for option chain metadata and Greeks.
- Whether moomoo or IBKR should handle actual order execution.
- How to reconcile differences in symbol format, contract identifiers, exchange routing, and time zones.
- How to detect stale quotes or mismatched bid/ask data between the two APIs.
- What fallback behavior should be used if one API is unavailable during market hours.

## OpenBurst Options Bot

Status: planned, not started.

Goal: build an OpenBurst options bot after researching suitable strategies, potentially including quantitative options hedging.

High-level idea:

- Research which OpenBurst-style option strategies are worth automating.
- Evaluate whether the bot should focus on directional trades, volatility trades, spreads, hedged option positions, or event-driven setups.
- Explore quantitative hedging methods such as delta hedging, portfolio Greeks limits, volatility exposure control, and drawdown-based risk reduction.
- Use paper trading first to test strategy logic before any live execution.
- Keep the strategy engine modular so different option strategies can be added or replaced later.

Expected reuse from this project:

- Moomoo paper-trading module from `broker/moomoo_paper.py`.
- Future moomoo and IBKR normalized market-data layer.
- Telegram command and notification patterns from `bot/handlers.py`.
- Existing Fintel and earnings signal modules if a strategy uses unusual trades, option flow, or earnings context.

Initial implementation notes:

- Start with research notes and backtest or paper-trading prototypes.
- Define risk controls before automation: max capital, max loss, max Greeks exposure, stop rules, and manual override.
- Store each generated signal, hedge decision, order plan, execution result, and final P/L for review.
- Keep live trading disabled until paper results and risk controls are acceptable.

Open design questions:

- What exactly "OpenBurst" should mean in this system: strategy family, signal source, product name, or execution framework.
- Which option strategies are best suited for quant hedging.
- Whether hedging should be stock-based, option-based, or portfolio-level.
- Which data provider should supply real-time Greeks, IV surface, and option chain snapshots.
- How much human approval should be required before execution.

## QQQI Dollar-Cost Averaging Quant Strategy

Status: planned, not started.

Goal: design and backtest a quantitative dollar-cost averaging strategy for QQQI, then decide whether it is suitable for paper trading and later automation.

High-level idea:

- Research QQQI's product behavior, distribution mechanics, underlying exposure, liquidity, drawdown profile, and tracking behavior.
- Compare simple fixed-schedule DCA against rule-based variants such as volatility-adjusted buying, drawdown-triggered buying, trend-filtered buying, and cash-reserve rebalancing.
- Include dividend or distribution assumptions in backtests where data is available.
- Evaluate performance across different budgets, contribution schedules, and risk controls.
- Use paper trading first before any real automated recurring purchase.

Expected reuse from this project:

- Moomoo paper-trading module from `broker/moomoo_paper.py`.
- Future moomoo and IBKR market-data integration for prices, dividends, and order execution.
- Telegram notifications for scheduled buys, skipped buys, portfolio status, and backtest summaries.
- Database patterns from `utils/db.py` for storing strategy runs, signals, trades, and performance snapshots.

Initial implementation notes:

- Start with a research notebook or script that downloads historical QQQI prices and distributions.
- Build a backtest with configurable starting capital, recurring contribution amount, buy frequency, and risk rules.
- Compare against benchmarks such as lump-sum buying, plain QQQ, and simple fixed-amount DCA.
- Track total return, max drawdown, volatility, cash drag, distribution reinvestment effect, and tax-sensitive assumptions if needed.
- Keep execution disabled until the backtest and paper-trading behavior are reviewed.

Open design questions:

- Which data source has reliable adjusted QQQI prices and distribution history.
- Whether distributions should be reinvested automatically or treated as cash income.
- What schedule to test: daily, weekly, biweekly, monthly, or drawdown-based.
- Whether the strategy should buy only QQQI or pair it with cash, QQQ, TQQQ, options, or hedges.
- What max position size, stop rules, or risk limits should apply before automation.
