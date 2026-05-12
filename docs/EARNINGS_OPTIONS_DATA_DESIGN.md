# Earnings Options Data Design

This document records the current architecture decisions for the earnings
options trading research system.

## Scope

For now, the data source constraint is:

```text
Use QuantConnect only for earnings calendar, fundamentals, historical news, historical prices, and historical options.
```

Do not use Nasdaq, yfinance, FMP, Alpha Vantage, or other providers for this
module unless the project decision changes later.

## Morning Data Pipeline

All scheduled times in this module are described in Eastern Time (ET).

The daily data pipeline should run at:

```text
08:15 ET
```

The Mac launchd agent uses the computer's local timezone. On this machine, that
is configured as Central Time, so the plist uses `07:15` local time to represent
`08:15 ET`.

The pipeline should run in this order:

```text
1. combined earnings + fundamentals sync
2. historical_equity_prices data_jobs
3. future Gemini analysis, after required data jobs complete
```

The earnings/fundamental sync should request:

```text
run_date = latest trading day
requested_start_date = today
requested_end_date = today + 60 calendar days
```

QuantConnect may return fewer than 60 days. Store whatever is returned. Do not
hard-code the current seven-day behavior as a business rule.

The morning batch is intentionally after QuantConnect's US equity daily update
window, so the equity price jobs can usually include the previous trading day's
latest daily and minute bars.

Recommended earnings/fundamental sync contents:

```text
upcoming earnings events
current fundamental snapshots for returned tickers
current event state updates
watchlist updates
```

Current implementation:

```text
scripts/run_earnings_qc_sync.py
earnings_options/qc_data_sync.py
qc/earnings_fundamentals_sync.py
qc/earnings_calendar.py
qc/fundamentals.py
com.chunwu.earningsqcsync.plist
scripts/run_morning_data_pipeline.py
```

The normal daily sync uses one combined QuantConnect backtest:

```text
qc/Z07_EarningsFundamentalsSync
```

The standalone earnings and fundamental downloaders remain as smoke tests and
fallback tools. They should not be used by the normal morning sync path because
they would consume two QC backtests for data that can be collected together.

To avoid unnecessary QuantConnect workload while keeping Gemini inputs complete:

```text
morning earnings sync: one combined earnings + fundamentals backtest
morning equity data jobs: run after the sync in the same pipeline
historical option chains: not part of the morning pipeline
historical news/options: queued as data_jobs, executed only when needed
Gemini analysis: scheduled after the morning pipeline, not before it
```

The morning pipeline also runs data readiness checks after the enrichment jobs.
Readiness checks do not download data; they only record whether the target
stock is ready for LLM research.

## Historical Equity Prices

`historical_equity_prices` jobs are executed by:

```text
scripts/run_data_jobs.py --job-type historical_equity_prices
earnings_options/data_job_worker.py
qc/equity_price_downloader.py
qc/Z08_EquityPriceDownload
```

Each job should use one QuantConnect backtest for one ticker. The backtest
collects both:

```text
daily OHLCV: report_date - 3 years to report_date + 2 trading days
minute OHLCV: report_date - 20 trading days to report_date + 2 trading days
```

If the report date is in the future, QuantConnect only returns bars through the
latest available data date. The manifest keeps the requested window while the
Parquet row count reflects the data actually returned.

Raw files are stored as Parquet:

```text
qc/data/equity/usa/daily/{ticker}.parquet
qc/data/equity/usa/minute/{ticker}/{YYYYMMDD}.parquet
```

PostgreSQL stores only manifests:

```text
equity_price_downloads
```

Do not pull second/tick data by default. Historical earnings-window minute data
should wait until historical earnings anchors are available.

## Technical Indicators

Production technical indicators should be computed locally from the downloaded
OHLCV Parquet files instead of launching additional QuantConnect jobs.

Rationale:

```text
local calculation does not consume extra QC backtests
indicator parameters can be changed and recomputed locally
Gemini should receive compact technical summaries, not raw bar series
QC indicator output remains useful as an occasional validation reference
```

The first production indicator layer should include daily indicators plus
minute-derived summaries:

```text
daily:
  SMA 20/50/100/200
  EMA 8/21
  RSI 14
  ATR 14
  20-day historical volatility
  60-day historical volatility
  52-week high/low distance
  5/10/20/60/120-day returns
  volume vs 20-day average

minute summary:
  VWAP
  intraday high/low
  close vs VWAP
  first 30-minute return
  last 30-minute return
  gap from previous close
  intraday range %
```

Current implementation:

```text
earnings_options/technical_indicators.py
scripts/build_technical_summary.py
equity_technical_summaries
```

`historical_equity_prices` jobs compute and upsert the technical summary after
the OHLCV Parquet files are written successfully. The summary stores key fields
as PostgreSQL columns and the full compact payload in `summary_json`.

Benchmark data:

```text
benchmarks = SPY, QQQ
```

When a `historical_equity_prices` job succeeds for a watchlist ticker, the
worker also ensures the same earnings window has benchmark OHLCV data and
technical summaries for `SPY` and `QQQ`. The first ticker for a report window
may trigger benchmark downloads; later tickers reuse existing benchmark
summaries and do not launch duplicate QC jobs for the same window.

QuantConnect indicator validation is available as a smoke test:

```text
qc/Z09_TechnicalIndicatorSmokeTest
qc/run_technical_indicator_smoke_test.py
```

The ACM daily indicator comparison on `2026-05-08` matched QuantConnect's
built-in daily indicators for SMA, EMA, RSI, ATR, and standard deviation to
floating-point precision. Keep this QC path as a future fallback or periodic
audit tool, but do not use it in the normal morning pipeline unless the project
decision changes.

Recommended first-stage eligibility rule:

```text
market_cap >= 10_000_000_000
report_time is known when available
report_date >= today
```

If QuantConnect does not provide market cap for a ticker:

```text
is_eligible = false
eligibility_reason = missing_market_cap
```

## Data Readiness

Readiness is checked before Gemini analysis.

Current implementation:

```text
earnings_options/data_readiness.py
scripts/check_data_readiness.py
earnings_data_readiness
```

Required data focuses on the target stock:

```text
target fundamentals
target equity price manifests
target technical summary
target historical earnings events
```

Context / optional data:

```text
SPY technical summary
QQQ technical summary
news summary
```

Future required data:

```text
option chain summary
```

Status values:

```text
ready_for_llm_research
missing_required_data
```

Benchmark context is deliberately not a primary signal. It exists only to help
Gemini judge whether a target ticker's pre-earnings move is stock-specific or
mostly market beta.

## LLM Strategy Input

The LLM should not query the database directly. Build an explicit JSON payload
first, review it, then pass that payload to the model-calling layer.

Current implementation:

```text
earnings_options/strategy_input_assembler.py
scripts/build_llm_strategy_input.py
```

Example:

```bash
/opt/miniconda3/bin/python3.13 scripts/build_llm_strategy_input.py \
  --ticker ACM \
  --budget 1000 \
  --output /tmp/acm_strategy_input.json
```

The payload schema is:

```text
earnings_options_strategy_input_v1
```

Core sections:

```text
metadata
ticker
budget
earnings_date
earnings_event
stock_data.fundamentals
stock_data.technical_summary
stock_data.benchmark_context
option_chain_data
news
historical_earnings
readiness
missing_data_that_would_improve_analysis
llm_instructions
```

The assembler intentionally does not call Gemini, TAMU, Claude, Moomoo, or any
trading API. It only reads local PostgreSQL rows and previously computed
summaries. The model caller should consume this payload and return a separate
strategy JSON.

## Gemini Strategy Analysis

The direct Gemini strategy caller is separate from the input assembler.

Current implementation:

```text
llm/gemini_client.py
earnings_options/gemini_strategy.py
scripts/run_gemini_strategy_analysis.py
```

Configuration:

```text
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-pro
```

`GOOGLE_API_KEY` and `GOOGLE_GENAI_API_KEY` are also accepted as fallbacks for
the API key.

Smoke test:

```bash
/opt/miniconda3/bin/python3.13 scripts/run_gemini_strategy_analysis.py --smoke-test
```

Run from a prepared payload:

```bash
/opt/miniconda3/bin/python3.13 scripts/run_gemini_strategy_analysis.py \
  --input /tmp/acm_strategy_input.json \
  --output /tmp/acm_gemini_strategy.json
```

Or build the input from the local database and call Gemini in one step:

```bash
/opt/miniconda3/bin/python3.13 scripts/run_gemini_strategy_analysis.py \
  --ticker ACM \
  --budget 1000 \
  --output /tmp/acm_gemini_strategy.json
```

The Gemini caller requests `application/json` output and validates that the
response contains exactly three defined-risk strategies. It does not submit
orders and does not call Moomoo.

## TAMU Claude Strategy Analysis

TAMU Claude is the preferred LLM path when using the user's TAMU daily credits.

Current implementation:

```text
llm/tamu_client.py
earnings_options/llm_strategy.py
scripts/run_tamu_strategy_analysis.py
```

Configuration:

```text
TAMU_API_KEY=...
TAMU_API_ENDPOINT=https://chat-api.tamu.ai/openai/chat/completions
TAMU_MODEL=protected.Claude Sonnet 4.6
```

The alternate TAMU account can be used with:

```text
TAMU_ALT_API_KEY=...
TAMU_ALT_BASE_URL=https://tti-api.tamus.ai
```

Smoke test:

```bash
/opt/miniconda3/bin/python3.13 scripts/run_tamu_strategy_analysis.py \
  --account alt \
  --model 'protected.Claude Sonnet 4.6' \
  --smoke-test
```

Run strategy analysis:

```bash
/opt/miniconda3/bin/python3.13 scripts/run_tamu_strategy_analysis.py \
  --account alt \
  --model 'protected.Claude Sonnet 4.6' \
  --input /tmp/acm_strategy_input.json \
  --output /tmp/acm_tamu_claude_strategy.json
```

For Claude models, the local TAMU wrapper sends `temperature=1` even when a
lower value is requested, because TAMU's Bedrock Claude route rejects other
temperatures when extended thinking is active. Very small `max_tokens` values
can also fail because they must exceed the hidden thinking budget, so the TAMU
strategy script uses larger token limits.

## Paper Order Drafts

LLM strategy JSON should be persisted before any broker action. The first
broker-facing layer creates order drafts only; it does not submit orders.

Current implementation:

```text
earnings_options/order_drafts.py
scripts/create_paper_order_drafts.py
scripts/list_paper_order_drafts.py
earnings_strategy_runs
paper_option_order_drafts
```

Create drafts from a TAMU Claude strategy result:

```bash
/opt/miniconda3/bin/python3.13 scripts/create_paper_order_drafts.py \
  --strategy-json /tmp/acm_tamu_claude_strategy.json \
  --input-json /tmp/acm_strategy_input_compact.json
```

List drafts:

```bash
/opt/miniconda3/bin/python3.13 scripts/list_paper_order_drafts.py \
  --strategy-run-id 1
```

Each draft stores:

```text
strategy_run_id
strategy_index
leg_index
action
option_type
expiry
strike
quantity
limit_price_hint
OCC symbol
Moomoo code candidate
broker_code
validation_status
validation_messages
raw_leg
```

Default validation is local-only:

```text
action is BUY or SELL
option_type is CALL or PUT
expiry parses as a date
strike > 0
quantity > 0
limit_price_hint > 0
```

The optional `--resolve-moomoo` flag calls Moomoo's option-chain API to map a
draft leg to an actual broker contract code. Do not use that flag as a trading
action; it only resolves symbols. The project still does not submit option
orders.

## Moomoo Contract Mapping And Quote Refresh

Paper option drafts can be mapped to Moomoo option contracts and refreshed with
live quote snapshots before any paper order is considered.

Current implementation:

```text
earnings_options/broker_mapping.py
scripts/refresh_paper_order_quotes.py
paper_option_quote_snapshots
```

Refresh one strategy run:

```bash
/opt/miniconda3/bin/python3.13 scripts/refresh_paper_order_quotes.py \
  --strategy-run-id 1
```

This step uses only Moomoo quote APIs:

```text
get_option_chain
get_market_snapshot
```

It does not call `place_order`.

The refresh stores:

```text
broker_code
quote_time
last_price
bid_price
ask_price
mid_price
bid_vol
ask_vol
volume
open_interest
implied_volatility
delta/gamma/theta/vega/rho
raw_snapshot
```

Moomoo US option codes may differ from OCC zero-padded symbols. For example:

```text
OCC:    ACM260515C00080000
Moomoo: US.ACM260515C80000
```

Do not submit an option order unless the draft status is `broker_mapped` and a
fresh quote snapshot exists.

## Pre-Trade Execution Plans

Before any paper order is submitted, create a strategy-level execution plan.
This step groups order drafts by `strategy_index`, reads the latest quote
snapshot for every leg, then runs local risk checks.

Current implementation:

```text
earnings_options/execution_plans.py
scripts/build_execution_plans.py
scripts/list_execution_plans.py
paper_option_execution_plans
```

Build plans:

```bash
/opt/miniconda3/bin/python3.13 scripts/build_execution_plans.py \
  --strategy-run-id 1
```

List plans:

```bash
/opt/miniconda3/bin/python3.13 scripts/list_execution_plans.py \
  --strategy-run-id 1
```

Pricing logic:

```text
BUY legs use ask price
SELL legs use bid price
conservative_net_debit = sum(BUY ask * qty * 100) - sum(SELL bid * qty * 100)
estimated_mid_debit = sum(BUY mid * qty * 100) - sum(SELL mid * qty * 100)
estimated_max_loss = max(conservative_net_debit, 0)
```

Default checks:

```text
structure_ok: legs have valid actions, option types, expiry, and quantities
budget_ok: conservative max loss <= strategy max_budget_to_use
liquidity_ok: valid bid/ask and max spread <= 35%
quote_fresh_ok: latest quote snapshot age <= 20 minutes
```

Only plans with all checks passing get:

```text
ready_for_paper_order
```

Otherwise the plan remains:

```text
needs_review
```

This step does not call Moomoo and does not place orders. It only reads local
order drafts and quote snapshots.

## Adjustment Suggestions

If an execution plan is `needs_review`, build adjusted-order suggestions before
manual approval or paper order submission.

Current implementation:

```text
earnings_options/adjustment_suggestions.py
scripts/build_adjustment_suggestions.py
scripts/list_adjustment_suggestions.py
paper_option_adjustment_suggestions
```

Build suggestions:

```bash
/opt/miniconda3/bin/python3.13 scripts/build_adjustment_suggestions.py \
  --strategy-run-id 1
```

List suggestions:

```bash
/opt/miniconda3/bin/python3.13 scripts/list_adjustment_suggestions.py \
  --strategy-run-id 1
```

The first version handles:

```text
reduce quantity to fit strategy budget
skip strategy when one contract still exceeds budget
skip strategy when liquidity/spread checks fail
use ask as suggested BUY limit
use bid as suggested SELL limit
```

Suggestions are separate rows. They do not mutate the original LLM strategy,
order drafts, or execution plans.

## Manual Approval To Paper Order Batch

After a Telegram manual approval is marked `approved`, convert the approved
adjustment suggestion into a staged paper order batch.

Current implementation:

```text
earnings_options/order_batches.py
scripts/stage_paper_order_batch.py
scripts/list_paper_order_batches.py
paper_option_order_batches
paper_option_order_batch_legs
```

Stage one approved request:

```bash
/opt/miniconda3/bin/python3.13 scripts/stage_paper_order_batch.py \
  --approval-id 1
```

List staged batches:

```bash
/opt/miniconda3/bin/python3.13 scripts/list_paper_order_batches.py \
  --approval-id 1
```

The staged batch stores broker-ready legs:

```text
broker_code
action
quantity
expiry
strike
suggested_limit_price
order_type = limit
status = staged
```

This step still does not call Moomoo and does not place orders.

## Paper Order Submission

Staged paper order batches can be dry-run or submitted to Moomoo paper trading.

Current implementation:

```text
earnings_options/batch_submission.py
scripts/submit_paper_order_batch.py
broker/moomoo_paper.py
```

Dry-run:

```bash
/opt/miniconda3/bin/python3.13 scripts/submit_paper_order_batch.py \
  --order-batch-id 1
```

Submit to paper trading:

```bash
/opt/miniconda3/bin/python3.13 scripts/submit_paper_order_batch.py \
  --order-batch-id 1 \
  --submit
```

Submission uses:

```text
TrdEnv.SIMULATE
OrderType.NORMAL
limit prices from staged batch legs
```

The first implementation submits individual option legs sequentially. It does
not yet submit a native multi-leg combo order, so fills can be partial or legged.
Use this only in paper trading until combo execution/risk handling is improved.

## Paper Order Monitoring

Submitted paper order batches should be monitored until terminal status.

Current implementation:

```text
earnings_options/order_monitor.py
scripts/refresh_paper_order_status.py
```

Refresh one batch:

```bash
/opt/miniconda3/bin/python3.13 scripts/refresh_paper_order_status.py \
  --order-batch-id 1 \
  --notify
```

The monitor reads Moomoo paper order status by `broker_order_id` and updates
each batch leg:

```text
status
dealt_qty
dealt_avg_price
last_err_msg
last_status_at
payload_json.latest_broker_order
```

Batch status is derived from leg statuses:

```text
filled
submitted
partial_filled
cancelled
attention_required
```

When `--notify` is used, status changes are pushed to Telegram. This does not
change orders; it only observes and records broker state.

## Position Monitoring And Exit Suggestions

Filled paper order batches can be valued against live Moomoo option quotes.

Current implementation:

```text
earnings_options/position_monitor.py
scripts/refresh_position_snapshot.py
scripts/list_position_snapshots.py
paper_option_position_snapshots
paper_option_exit_plans
```

Refresh one filled batch:

```bash
/opt/miniconda3/bin/python3.13 scripts/refresh_position_snapshot.py \
  --order-batch-id 1 \
  --notify
```

The first version computes:

```text
entry_net_debit
current_exit_value
unrealized_pl
unrealized_pl_pct
max_profit
max_loss
```

Exit suggestion rules:

```text
take_profit when unrealized_pl_pct >= 50
stop_loss when unrealized_pl_pct <= -50
review_near_expiry when expiry is <= 1 calendar day away
hold otherwise
```

Exit legs are generated as closing trades:

```text
long leg -> SELL at bid
short leg -> BUY at ask
```

This step does not place exit orders.

## Repository Quality Hooks

Git hooks are installed through:

```text
core.hooksPath = .githooks
```

The hook entrypoints are:

```text
.githooks/pre-commit
.githooks/pre-push
```

Both call:

```text
scripts/repo_quality_check.sh
```

The quality check runs `py_compile`, `git diff --check`, and refuses to commit
local secret/runtime paths such as `.env`, session files, logs, Chrome profile
state, and `qc/data/`.

## PostgreSQL vs Parquet

Use PostgreSQL for business state:

```text
sync runs
current earnings events
raw earnings event snapshots
fundamental snapshots
event changes
watchlist state
download manifests
analysis summaries
trade plans
```

Use Parquet for large historical market data:

```text
minute option chain data
historical equity minute/second data
large raw exports from QuantConnect
```

Do not store full minute option chains in PostgreSQL. PostgreSQL should store
only paths, metadata, and computed summaries for those files.

## Proposed PostgreSQL Tables

### `qc_earnings_sync_runs`

Tracks every QuantConnect earnings/fundamental sync.

Suggested fields:

```text
id
started_at
finished_at
run_date
requested_start_date
requested_end_date
source
status
raw_event_count
fundamental_count
eligible_count
error_message
```

### `qc_earnings_raw_events`

Append-only raw earnings events from each sync.

Suggested fields:

```text
id
sync_run_id
as_of_date
ticker
report_date
report_time
eps_estimate
source_payload
created_at
```

Suggested unique key:

```text
unique(sync_run_id, ticker, report_date, report_time)
```

### `qc_fundamental_snapshots`

Stores the current QuantConnect fundamental snapshot for each returned ticker.

Core fields should be columns:

```text
id
sync_run_id
ticker
snapshot_date
company_name
market_cap
sector_code
industry_group_code
industry_code
exchange_id
country_id
currency_id
shares_outstanding
revenue_ttm
gross_profit_ttm
operating_income_ttm
net_income_ttm
eps_ttm
pe_ratio
forward_pe_ratio
pb_ratio
ps_ratio
pcf_ratio
ev_to_ebitda
ev_to_revenue
roe
roa
current_ratio
quick_ratio
gross_margin
net_margin
fundamental_json
created_at
```

Keep the complete QuantConnect payload in `fundamental_json` so the schema can
expand without frequent table migrations.

### `qc_earnings_current_events`

Current upcoming earnings state.

Suggested fields:

```text
id
ticker
company_name
report_date
report_time
eps_estimate
market_cap
exchange_id
sector_code
industry_code
first_seen_at
last_seen_at
last_sync_run_id
seen_count
missing_count
is_active
inactive_reason
is_eligible
eligibility_reason
updated_at
```

Recommended uniqueness:

```text
one active event per ticker
```

Rationale: the system follows the ticker's next upcoming earnings event. If the
date or time changes, update the active row and record the change.

### `qc_earnings_event_changes`

Append-only change log for current events.

Suggested fields:

```text
id
current_event_id
ticker
field_name
old_value
new_value
sync_run_id
changed_at
```

Track changes in:

```text
report_date
report_time
eps_estimate
market_cap
company_name
is_eligible
eligibility_reason
```

### `earnings_watchlist`

Tracks events selected for deeper analysis.

Suggested fields:

```text
id
current_event_id
ticker
status
selected_at
selected_reason
analysis_start_date
report_date
report_time
market_cap
last_fundamental_snapshot_id
notes
updated_at
```

Initial statuses:

```text
watching
inactive
expired
```

Later statuses can include:

```text
analyzing
strategy_ready
paper_trade_planned
traded
skipped
```

## Incremental Update Rules

Each sync should create a `sync_run`, insert raw rows, then upsert current
events.

For each returned ticker:

```text
if active current event exists:
    compare report_date/report_time/eps_estimate/market_cap/company_name/etc.
    write event_changes for changed fields
    update current event
    seen_count += 1
    missing_count = 0
else:
    insert new active current event
```

For active current events not returned in the latest sync:

```text
missing_count += 1
```

Deactivate when:

```text
report_date < today -> inactive_reason = expired
missing_count >= 3 -> inactive_reason = missing_from_source
```

Do not delete events just because they are absent from one QuantConnect sync.

## Historical Enrichment

Historical enrichment is separate from the morning earnings/fundamental sync.

When a ticker enters `earnings_watchlist`, enqueue enrichment jobs:

```text
historical earnings anchors
historical company news
historical market news
historical industry/peer news
historical equity prices
historical option chains
```

Do not re-run full historical enrichment every night. Cache results and only
fill missing windows.

## Historical Earnings Timing

`historical_earnings` jobs use QuantConnect as the historical earnings anchor
source, then enrich each anchor with SEC EDGAR filing timing.

Current implementation:

```text
qc/historical_earnings.py
qc/Z05_HistoricalEarningsSmokeTest
earnings_options/sec_earnings.py
historical_earnings_events
```

Source priority:

```text
1. QuantConnect Morningstar EarningReports for historical anchor rows
2. SEC EDGAR submissions API for acceptanceDateTime and filing URL
3. release_session inferred from SEC acceptanceDateTime in ET
```

SEC matching rules:

```text
preferred forms: 8-K / 8-K/A with Item 2.02
fallback forms: 6-K / 6-K/A / 10-Q / 10-K
search window: anchor date +/- 2 calendar days
```

Release session classification:

```text
04:00-09:30 ET -> premarket
09:30-16:00 ET -> regular
16:00-20:00 ET -> postmarket
other times -> extended
missing time -> unknown
```

Confidence rules:

```text
high: 8-K Item 2.02 near the anchor date
medium: 8-K/6-K near the anchor date but without Item 2.02
low: fallback form, stale QC file_date, or no exact SEC match
```

Important QC caveat:

```text
QC file_date can occasionally be stale and earlier than period_ending_date.
When that happens, use observed_date as the anchor and record this in notes.
```

## News Windows

Use QuantConnect TiingoNews.

Preserve three news layers:

```text
company_news: target ticker
industry_news: sector ETF and major peers
market_news: SPY, QQQ, VIX-related context where available
```

Suggested windows:

```text
historical earnings windows: T-10 to T+2
current earnings window: T-14 to T+1, updated incrementally
background window: last 90 days
```

Store raw articles and separate summaries. LLMs should read summaries and
ranked key articles, not every raw article.

## Historical Option Chain

Use QuantConnect minute-resolution option data.

`historical_option_chain` jobs are executed by:

```text
scripts/run_data_jobs.py --job-type historical_option_chain
earnings_options/data_job_worker.py
qc/option_chain_downloader.py
qc/Z06_OptionChainDownload
```

The current worker downloads only the current watchlist earnings window:

```text
T-5 trading days to T+2 trading days
DTE 0-180
strike rank -250 to +250
include weeklys
minute resolution
```

Historical prior-earnings option windows should be added later after the option
summary layer is stable, because they can create many QC backtests and large
Parquet files.

Option-chain summary v1 is generated locally from downloaded option Parquet
files and the target ticker's equity technical summary spot price.

Current implementation:

```text
earnings_options/option_chain_summary.py
scripts/build_option_chain_summary.py
option_chain_summaries
```

Summary v1 intentionally does not require delta, IV, or open interest. It uses
available trade/quote bars plus OCC symbol parsing.

Core fields:

```text
front_expiry
atm_strike
atm_call_mid
atm_put_mid
atm_straddle_mid
implied_move_pct
median_spread_pct
atm_spread_pct
total_call_volume
total_put_volume
call_put_volume_ratio
top_volume_contracts
top_premium_contracts
straddle_trend_by_day
liquidity_score
volatility_pricing_score
directional_skew_score
```

Skew is a moneyness proxy:

```text
5% OTM put mid / ATM put mid
5% OTM call mid / ATM call mid
put_call_skew_proxy = put_ratio - call_ratio
```

Store raw option chain files as Parquet:

```text
qc/data/option/usa/minute/{ticker}/{YYYYMMDD}.parquet
```

PostgreSQL should store a download manifest and computed metrics, not the full
minute chain.

Suggested manifest fields:

```text
id
ticker
trade_date
window_id
source
resolution
filter_preset
min_dte
max_dte
min_strike_rank
max_strike_rank
path
contract_count
row_count
file_size
status
error_message
created_at
updated_at
```

Recommended historical window:

```text
T-5 to T+2
```

Recommended default option-chain filter:

```text
filter_preset = earnings_wide_v1
include_weeklys = true
resolution = minute
min_dte = 0
max_dte = 180
min_strike_rank = -250
max_strike_rank = 250
```

Rationale:

```text
This is intentionally wider than an ATM-only chain so deep ITM/OTM positioning
is still visible, but it avoids downloading every LEAPS contract by default.
LEAPS/deep-history jobs should be triggered only by unusual-trade evidence or
manual research needs.
```

The raw data keeps integer prices in QuantConnect export units:

```text
price_integer = USD * 10000
```

Analysis code should convert to dollar prices in derived summaries.

## QuantConnect Tests Completed

### Upcoming Earnings + Fundamentals

Tested `2026-05-11` earnings tickers.

```text
earnings tickers: 106
fundamental rows with market_cap: 94
market_cap >= 10B: 15
```

### Historical Earnings Anchors

Tested CEG from `2023-01-01` to `2026-05-08`.

Result:

```text
QC Fundamental EarningReports can provide historical anchor dates.
FileDate is useful, but it is not guaranteed to be exact earnings release time.
Before/after-market timing is not available from this historical fundamental test.
```

### Option Chain

Tested CEG broad full-chain minute option download on `2025-05-06` before
narrowing the default preset.

Result:

```text
contracts: 1516
rows: 591,240
output: qc/data/option/usa/minute/ceg/20250506.parquet
```

This replaced the narrower ATM-focused option downloader from a separate
project. The current implementation is physically isolated inside this project.

Current default code now uses the `earnings_wide_v1` preset:

```text
DTE 0-180
strike rank -250 to +250
```
