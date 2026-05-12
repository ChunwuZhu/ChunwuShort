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
- Existing and future market-data helpers for option chains, quotes, and position state.
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
