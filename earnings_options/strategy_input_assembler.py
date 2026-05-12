"""Build compact LLM inputs for earnings option strategy research."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from utils.db import (
    EarningsDataReadiness,
    EquityTechnicalSummary,
    HistoricalEarningsEvent,
    OptionChainSummary,
    QCEarningsCurrentEvent,
    QCFundamentalSnapshot,
    SessionLocal,
)

BENCHMARK_TICKERS = ("SPY", "QQQ")
DEFAULT_HISTORICAL_EARNINGS_LIMIT = 12


def build_strategy_input(
    *,
    ticker: str,
    budget: float | Decimal | str,
    report_date: date | str | None = None,
    historical_earnings_limit: int = DEFAULT_HISTORICAL_EARNINGS_LIMIT,
    include_full_fundamental_json: bool = False,
) -> dict[str, Any]:
    """Assemble database state into the payload consumed by the LLM layer."""
    ticker_upper = ticker.upper()
    report_day = _parse_day(report_date) if report_date else None
    db = SessionLocal()
    try:
        event = _find_event(db, ticker_upper, report_day)
        if event is None:
            raise ValueError(f"No active earnings event found for {ticker_upper}")

        window_id = f"earnings_{event.report_date.strftime('%Y%m%d')}"
        fundamental = _latest_fundamental(db, ticker_upper)
        technical = _latest_technical(db, ticker_upper, window_id)
        option_summary = _latest_option_summary(db, ticker_upper, window_id)
        historical_earnings = _historical_earnings(db, ticker_upper, historical_earnings_limit)
        readiness = _latest_readiness(db, event.id)
        benchmarks = {
            benchmark: _technical_payload(_latest_technical(db, benchmark, window_id))
            for benchmark in BENCHMARK_TICKERS
        }

        payload = {
            "metadata": {
                "schema": "earnings_options_strategy_input_v1",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "source": "local_postgresql_and_quantconnect_parquet_summaries",
                "execution_mode": "analysis_only",
                "data_source_constraint": "quantconnect_only_for_market_data",
                "notes": [
                    "This payload is for LLM strategy research and paper-trading planning only.",
                    "Benchmark data is context only; target-stock data should drive the analysis.",
                ],
            },
            "ticker": ticker_upper,
            "budget": _to_float(Decimal(str(budget))),
            "earnings_date": event.report_date.isoformat(),
            "earnings_event": _event_payload(event),
            "stock_data": {
                "fundamentals": _fundamental_payload(fundamental, include_full_fundamental_json),
                "technical_summary": _technical_payload(technical),
                "benchmark_context": benchmarks,
            },
            "option_chain_data": _option_payload(option_summary),
            "news": {
                "status": "not_implemented",
                "company_news": [],
                "industry_news": [],
                "market_news": [],
            },
            "historical_earnings": [
                _historical_earnings_payload(row) for row in historical_earnings
            ],
            "readiness": _readiness_payload(readiness),
            "missing_data_that_would_improve_analysis": _missing_data(
                fundamental=fundamental,
                technical=technical,
                option_summary=option_summary,
                historical_earnings=historical_earnings,
                readiness=readiness,
                benchmarks=benchmarks,
            ),
            "llm_instructions": {
                "primary_focus": "target_stock",
                "strategy_requirement": "defined_risk_options_only",
                "output_use": "moomoo_paper_trading_plan",
                "do_not": [
                    "Do not place orders.",
                    "Do not treat benchmark context as the main signal.",
                    "Do not recommend undefined-risk naked short options.",
                ],
            },
        }
        return _clean(payload)
    finally:
        db.close()


def _find_event(db, ticker: str, report_date: date | None) -> QCEarningsCurrentEvent | None:
    query = db.query(QCEarningsCurrentEvent).filter(
        QCEarningsCurrentEvent.ticker == ticker,
        QCEarningsCurrentEvent.is_active.is_(True),
    )
    if report_date:
        query = query.filter(QCEarningsCurrentEvent.report_date == report_date)
    return query.order_by(QCEarningsCurrentEvent.report_date.asc(), QCEarningsCurrentEvent.id.desc()).first()


def _latest_fundamental(db, ticker: str) -> QCFundamentalSnapshot | None:
    return (
        db.query(QCFundamentalSnapshot)
        .filter(QCFundamentalSnapshot.ticker == ticker)
        .order_by(QCFundamentalSnapshot.snapshot_date.desc(), QCFundamentalSnapshot.id.desc())
        .first()
    )


def _latest_technical(db, ticker: str, window_id: str) -> EquityTechnicalSummary | None:
    return (
        db.query(EquityTechnicalSummary)
        .filter(EquityTechnicalSummary.ticker == ticker, EquityTechnicalSummary.window_id == window_id)
        .order_by(EquityTechnicalSummary.as_of_date.desc(), EquityTechnicalSummary.id.desc())
        .first()
    )


def _latest_option_summary(db, ticker: str, window_id: str) -> OptionChainSummary | None:
    return (
        db.query(OptionChainSummary)
        .filter(OptionChainSummary.ticker == ticker, OptionChainSummary.window_id == window_id)
        .order_by(OptionChainSummary.as_of_date.desc(), OptionChainSummary.id.desc())
        .first()
    )


def _historical_earnings(db, ticker: str, limit: int) -> list[HistoricalEarningsEvent]:
    return (
        db.query(HistoricalEarningsEvent)
        .filter(HistoricalEarningsEvent.ticker == ticker)
        .order_by(HistoricalEarningsEvent.report_date.desc(), HistoricalEarningsEvent.id.desc())
        .limit(limit)
        .all()
    )


def _latest_readiness(db, event_id: int) -> EarningsDataReadiness | None:
    return (
        db.query(EarningsDataReadiness)
        .filter(EarningsDataReadiness.current_event_id == event_id)
        .order_by(EarningsDataReadiness.checked_at.desc(), EarningsDataReadiness.id.desc())
        .first()
    )


def _event_payload(event: QCEarningsCurrentEvent) -> dict[str, Any]:
    return {
        "current_event_id": event.id,
        "ticker": event.ticker,
        "company_name": event.company_name,
        "report_date": event.report_date,
        "report_time": event.report_time,
        "eps_estimate": event.eps_estimate,
        "market_cap": event.market_cap,
        "exchange_id": event.exchange_id,
        "sector_code": event.sector_code,
        "industry_code": event.industry_code,
        "first_seen_at": event.first_seen_at,
        "last_seen_at": event.last_seen_at,
        "seen_count": event.seen_count,
        "is_eligible": event.is_eligible,
        "eligibility_reason": event.eligibility_reason,
    }


def _fundamental_payload(
    snapshot: QCFundamentalSnapshot | None,
    include_full_fundamental_json: bool,
) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    payload = {
        "snapshot_id": snapshot.id,
        "snapshot_date": snapshot.snapshot_date,
        "company_name": snapshot.company_name,
        "market_cap": snapshot.market_cap,
        "sector_code": snapshot.sector_code,
        "industry_group_code": snapshot.industry_group_code,
        "industry_code": snapshot.industry_code,
        "exchange_id": snapshot.exchange_id,
        "country_id": snapshot.country_id,
        "currency_id": snapshot.currency_id,
        "shares_outstanding": snapshot.shares_outstanding,
        "revenue_ttm": snapshot.revenue_ttm,
        "gross_profit_ttm": snapshot.gross_profit_ttm,
        "operating_income_ttm": snapshot.operating_income_ttm,
        "net_income_ttm": snapshot.net_income_ttm,
        "eps_ttm": snapshot.eps_ttm,
        "pe_ratio": snapshot.pe_ratio,
        "forward_pe_ratio": snapshot.forward_pe_ratio,
        "pb_ratio": snapshot.pb_ratio,
        "ps_ratio": snapshot.ps_ratio,
        "pcf_ratio": snapshot.pcf_ratio,
        "ev_to_ebitda": snapshot.ev_to_ebitda,
        "ev_to_revenue": snapshot.ev_to_revenue,
        "roe": snapshot.roe,
        "roa": snapshot.roa,
        "current_ratio": snapshot.current_ratio,
        "quick_ratio": snapshot.quick_ratio,
        "gross_margin": snapshot.gross_margin,
        "net_margin": snapshot.net_margin,
    }
    if include_full_fundamental_json:
        payload["raw_quantconnect_fundamental"] = snapshot.fundamental_json
    return payload


def _technical_payload(summary: EquityTechnicalSummary | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    payload = dict(summary.summary_json or {})
    payload["technical_summary_id"] = summary.id
    payload["columns"] = {
        "trend_regime": summary.trend_regime,
        "momentum_regime": summary.momentum_regime,
        "volatility_regime": summary.volatility_regime,
        "volume_regime": summary.volume_regime,
        "close_price": summary.close_price,
        "return_5d_pct": summary.return_5d_pct,
        "return_20d_pct": summary.return_20d_pct,
        "return_60d_pct": summary.return_60d_pct,
        "rsi_14": summary.rsi_14,
        "atr_14_pct": summary.atr_14_pct,
        "hv_20": summary.hv_20,
        "hv_60": summary.hv_60,
        "distance_to_52w_high_pct": summary.distance_to_52w_high_pct,
        "distance_to_52w_low_pct": summary.distance_to_52w_low_pct,
        "latest_close_vs_vwap_pct": summary.latest_close_vs_vwap_pct,
    }
    return payload


def _option_payload(summary: OptionChainSummary | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    payload = dict(summary.summary_json or {})
    payload["option_chain_summary_id"] = summary.id
    payload["columns"] = {
        "spot_price": summary.spot_price,
        "front_expiry": summary.front_expiry,
        "days_to_expiry": summary.days_to_expiry,
        "atm_strike": summary.atm_strike,
        "atm_call_mid": summary.atm_call_mid,
        "atm_put_mid": summary.atm_put_mid,
        "atm_straddle_mid": summary.atm_straddle_mid,
        "implied_move_pct": summary.implied_move_pct,
        "median_spread_pct": summary.median_spread_pct,
        "atm_spread_pct": summary.atm_spread_pct,
        "total_call_volume": summary.total_call_volume,
        "total_put_volume": summary.total_put_volume,
        "call_put_volume_ratio": summary.call_put_volume_ratio,
        "liquidity_score": summary.liquidity_score,
        "volatility_pricing_score": summary.volatility_pricing_score,
        "directional_skew_score": summary.directional_skew_score,
    }
    return payload


def _historical_earnings_payload(row: HistoricalEarningsEvent) -> dict[str, Any]:
    return {
        "historical_earnings_event_id": row.id,
        "report_date": row.report_date,
        "qc_observed_date": row.qc_observed_date,
        "qc_file_date": row.qc_file_date,
        "period_ending_date": row.period_ending_date,
        "basic_eps_3m": row.basic_eps_3m,
        "diluted_eps_3m": row.diluted_eps_3m,
        "release_session": row.release_session,
        "release_time_confidence": row.release_time_confidence,
        "sec_acceptance_datetime": row.sec_acceptance_datetime,
        "sec_form_type": row.sec_form_type,
        "sec_items": row.sec_items,
        "source_url": row.source_url,
        "notes": row.notes,
    }


def _readiness_payload(readiness: EarningsDataReadiness | None) -> dict[str, Any] | None:
    if readiness is None:
        return None
    return {
        "readiness_id": readiness.id,
        "status": readiness.status,
        "required_ready": readiness.required_ready,
        "optional_context_ready": readiness.optional_context_ready,
        "required_missing_count": readiness.required_missing_count,
        "optional_missing_count": readiness.optional_missing_count,
        "checked_at": readiness.checked_at,
        "details": readiness.details_json,
    }


def _missing_data(
    *,
    fundamental: QCFundamentalSnapshot | None,
    technical: EquityTechnicalSummary | None,
    option_summary: OptionChainSummary | None,
    historical_earnings: list[HistoricalEarningsEvent],
    readiness: EarningsDataReadiness | None,
    benchmarks: dict[str, dict[str, Any] | None],
) -> list[str]:
    missing = []
    if fundamental is None:
        missing.append("target QuantConnect fundamental snapshot")
    if technical is None:
        missing.append("target equity technical summary")
    if option_summary is None:
        missing.append("current earnings-window option-chain summary")
    if not historical_earnings:
        missing.append("historical earnings events and SEC timing enrichment")
    for ticker, payload in benchmarks.items():
        if payload is None:
            missing.append(f"{ticker} benchmark technical context")
    if readiness is None:
        missing.append("latest data readiness row")
    missing.append("company/industry/market news summaries are not implemented yet")
    return missing


def _parse_day(value: date | str | None) -> date:
    if isinstance(value, date):
        return value
    if not value:
        raise ValueError("report_date is required")
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return datetime.strptime(text, "%Y-%m-%d").date()


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, Decimal):
        return _to_float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)
