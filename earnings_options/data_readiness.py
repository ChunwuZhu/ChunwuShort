"""Data readiness checks before earnings-options LLM analysis."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func

from utils.db import (
    EarningsDataReadiness,
    EarningsWatchlist,
    EquityPriceDownload,
    EquityTechnicalSummary,
    HistoricalEarningsEvent,
    OptionChainSummary,
    QCEarningsCurrentEvent,
    QCFundamentalSnapshot,
    SessionLocal,
)

BENCHMARK_TICKERS = ("SPY", "QQQ")


def check_watchlist_readiness(*, limit: int | None = None) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        query = (
            db.query(EarningsWatchlist)
            .filter(EarningsWatchlist.status == "watching")
            .order_by(EarningsWatchlist.report_date.asc(), EarningsWatchlist.id.asc())
        )
        if limit:
            query = query.limit(limit)
        results = []
        for watch in query.all():
            event = db.query(QCEarningsCurrentEvent).filter(QCEarningsCurrentEvent.id == watch.current_event_id).first()
            if event is None:
                continue
            result = check_event_readiness(db, event)
            _upsert_readiness(db, event, result)
            results.append(result)
        db.commit()
        return results
    finally:
        db.close()


def check_ticker_readiness(ticker: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        event = (
            db.query(QCEarningsCurrentEvent)
            .filter(QCEarningsCurrentEvent.ticker == ticker.upper(), QCEarningsCurrentEvent.is_active.is_(True))
            .order_by(QCEarningsCurrentEvent.report_date.asc(), QCEarningsCurrentEvent.id.desc())
            .first()
        )
        if event is None:
            raise ValueError(f"No active earnings current event found for {ticker.upper()}")
        result = check_event_readiness(db, event)
        _upsert_readiness(db, event, result)
        db.commit()
        return result
    finally:
        db.close()


def check_event_readiness(db, event: QCEarningsCurrentEvent) -> dict[str, Any]:
    ticker = event.ticker.upper()
    window_id = f"earnings_{event.report_date.strftime('%Y%m%d')}"
    checks = {}

    fundamental = _latest_fundamental(db, ticker)
    checks["target_fundamentals"] = _check_result(
        fundamental is not None,
        "required",
        id_=fundamental.id if fundamental else None,
        message="latest QuantConnect fundamental snapshot",
    )

    technical = _latest_technical(db, ticker, window_id)
    checks["target_technical_summary"] = _check_result(
        technical is not None,
        "required",
        id_=technical.id if technical else None,
        as_of_date=technical.as_of_date.isoformat() if technical else None,
        message="target equity OHLCV and technical summary",
    )

    price_manifest_count = _price_manifest_count(db, ticker, window_id)
    checks["target_price_manifest"] = _check_result(
        price_manifest_count > 0,
        "required",
        count=price_manifest_count,
        message="target equity price parquet manifests",
    )

    historical_earnings_count = _historical_earnings_count(db, ticker)
    checks["target_historical_earnings"] = _check_result(
        historical_earnings_count > 0,
        "required",
        count=historical_earnings_count,
        message="historical earnings anchors and SEC timing enrichment",
    )

    benchmark_ids = {}
    for benchmark in BENCHMARK_TICKERS:
        summary = _latest_technical(db, benchmark, window_id)
        key = f"benchmark_{benchmark.lower()}_technical_summary"
        checks[key] = _check_result(
            summary is not None,
            "optional",
            id_=summary.id if summary else None,
            as_of_date=summary.as_of_date.isoformat() if summary else None,
            message=f"{benchmark} benchmark technical context",
        )
        benchmark_ids[benchmark] = summary.id if summary else None

    option_summary = _latest_option_summary(db, ticker, window_id)
    checks["option_chain_summary"] = _check_result(
        option_summary is not None,
        "future_required",
        id_=option_summary.id if option_summary else None,
        as_of_date=option_summary.as_of_date.isoformat() if option_summary else None,
        message="option-chain pricing/liquidity summary; required before option strategy generation",
    )
    checks["news_summary"] = _check_result(
        False,
        "optional",
        message="not implemented yet; optional context for first readiness version",
    )

    required_missing = [
        name for name, item in checks.items()
        if item["level"] == "required" and not item["ready"]
    ]
    optional_missing = [
        name for name, item in checks.items()
        if item["level"] == "optional" and not item["ready"]
    ]
    status = "ready_for_llm_research" if not required_missing else "missing_required_data"

    return {
        "current_event_id": event.id,
        "ticker": ticker,
        "report_date": event.report_date.isoformat(),
        "status": status,
        "required_ready": not required_missing,
        "optional_context_ready": not optional_missing,
        "required_missing": required_missing,
        "optional_missing": optional_missing,
        "checks": checks,
        "ids": {
            "fundamental_snapshot_id": fundamental.id if fundamental else None,
            "technical_summary_id": technical.id if technical else None,
            "benchmark_spy_summary_id": benchmark_ids["SPY"],
            "benchmark_qqq_summary_id": benchmark_ids["QQQ"],
        },
        "counts": {
            "target_price_manifests": price_manifest_count,
            "historical_earnings": historical_earnings_count,
        },
    }


def _upsert_readiness(db, event: QCEarningsCurrentEvent, result: dict[str, Any]) -> int:
    existing = (
        db.query(EarningsDataReadiness)
        .filter(EarningsDataReadiness.current_event_id == event.id)
        .first()
    )
    if existing is None:
        existing = EarningsDataReadiness(
            current_event_id=event.id,
            ticker=event.ticker,
            report_date=event.report_date,
        )
        db.add(existing)

    ids = result["ids"]
    counts = result["counts"]
    existing.status = result["status"]
    existing.required_missing_count = len(result["required_missing"])
    existing.optional_missing_count = len(result["optional_missing"])
    existing.required_ready = result["required_ready"]
    existing.optional_context_ready = result["optional_context_ready"]
    existing.latest_fundamental_snapshot_id = ids["fundamental_snapshot_id"]
    existing.technical_summary_id = ids["technical_summary_id"]
    existing.benchmark_spy_summary_id = ids["benchmark_spy_summary_id"]
    existing.benchmark_qqq_summary_id = ids["benchmark_qqq_summary_id"]
    existing.historical_earnings_count = counts["historical_earnings"]
    existing.details_json = result
    existing.checked_at = func.now()
    db.flush()
    return existing.id


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


def _price_manifest_count(db, ticker: str, window_id: str) -> int:
    return (
        db.query(EquityPriceDownload)
        .filter(EquityPriceDownload.ticker == ticker, EquityPriceDownload.window_id == window_id)
        .count()
    )


def _historical_earnings_count(db, ticker: str) -> int:
    return db.query(HistoricalEarningsEvent).filter(HistoricalEarningsEvent.ticker == ticker).count()


def _latest_option_summary(db, ticker: str, window_id: str) -> OptionChainSummary | None:
    return (
        db.query(OptionChainSummary)
        .filter(OptionChainSummary.ticker == ticker, OptionChainSummary.window_id == window_id)
        .order_by(OptionChainSummary.as_of_date.desc(), OptionChainSummary.id.desc())
        .first()
    )


def _check_result(ready: bool, level: str, **details) -> dict[str, Any]:
    payload = {"ready": ready, "level": level}
    payload.update(details)
    return payload
