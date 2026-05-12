"""Worker for earnings-options data enrichment jobs."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas_market_calendars as mcal
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from earnings_options.technical_indicators import build_technical_summary
from earnings_options.option_chain_summary import build_option_chain_summary
from earnings_options.sec_earnings import enrich_earnings_anchor, parse_acceptance_datetime
from qc.equity_price_downloader import download_equity_prices
from qc.historical_earnings import download_historical_earnings
from qc.option_chain_downloader import download_option_chain
from utils.db import (
    DataJob,
    EquityPriceDownload,
    EquityTechnicalSummary,
    HistoricalEarningsEvent,
    OptionChainDownload,
    OptionChainSummary,
    SessionLocal,
)

NYSE = mcal.get_calendar("NYSE")
BENCHMARK_TICKERS = ("SPY", "QQQ")


def run_pending_jobs(*, job_type: str = "historical_equity_prices", limit: int = 1) -> list[dict[str, Any]]:
    if job_type not in {"historical_equity_prices", "historical_earnings", "historical_option_chain"}:
        raise ValueError(f"Unsupported job_type: {job_type}")

    results = []
    for _ in range(limit):
        job = _claim_next_job(job_type)
        if job is None:
            break
        results.append(run_job(job.id))
    return results


def run_job(job_id: int) -> dict[str, Any]:
    db = SessionLocal()
    job = db.query(DataJob).filter(DataJob.id == job_id).first()
    if job is None:
        db.close()
        raise ValueError(f"DataJob {job_id} not found")

    try:
        ticker = (job.ticker or "").upper()
        if not ticker:
            raise ValueError("Job ticker is required")
        if job.job_type == "historical_equity_prices":
            result = _run_historical_equity_prices(db, job, ticker)
        elif job.job_type == "historical_earnings":
            result = _run_historical_earnings(db, job, ticker)
        elif job.job_type == "historical_option_chain":
            result = _run_historical_option_chain(db, job, ticker)
        else:
            raise ValueError(f"Unsupported job_type: {job.job_type}")

        job.status = "success"
        job.result = result
        job.finished_at = func.now()
        db.commit()
        return {"job_id": job.id, "status": "success", "ticker": ticker, **_result_summary(job.job_type, result)}
    except Exception as exc:
        db.rollback()
        job = db.query(DataJob).filter(DataJob.id == job_id).first()
        if job is not None:
            job.status = "failed"
            job.error_message = str(exc)
            job.finished_at = func.now()
            db.commit()
        raise
    finally:
        db.close()


def _run_historical_equity_prices(db, job: DataJob, ticker: str) -> dict[str, Any]:
    params = job.params or {}
    report_date = _parse_day(params.get("report_date"))
    windows = equity_price_windows(report_date)
    download_result = download_equity_prices(ticker=ticker, **windows)
    _record_equity_downloads(db, ticker, report_date, windows, download_result)
    technical_summary = build_technical_summary(ticker=ticker, report_date=report_date, windows=windows)
    technical_summary_id = _upsert_technical_summary(db, technical_summary, windows)
    benchmark_results = _ensure_benchmark_summaries(db, report_date, windows, exclude={ticker})
    return {
        "ticker": ticker,
        "windows": {key: value.isoformat() for key, value in windows.items()},
        "download": download_result,
        "technical_summary_id": technical_summary_id,
        "benchmarks": benchmark_results,
    }


def _run_historical_earnings(db, job: DataJob, ticker: str) -> dict[str, Any]:
    params = job.params or {}
    report_date = _parse_day(params.get("report_date"))
    start = _parse_day(params.get("start_date")) if params.get("start_date") else report_date - timedelta(days=365 * 4)
    end = _parse_day(params.get("end_date")) if params.get("end_date") else report_date
    rows = download_historical_earnings(ticker=ticker, start=start, end=end, save_outputs=True)
    saved_ids = []
    for row in rows:
        event = _upsert_historical_earnings_event(db, ticker, row)
        if event is not None:
            saved_ids.append(event.id)
    return {
        "ticker": ticker,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "qc_row_count": len(rows),
        "historical_earnings_event_ids": saved_ids,
    }


def _result_summary(job_type: str, result: dict[str, Any]) -> dict[str, Any]:
    if job_type == "historical_equity_prices":
        return {
            "files": len(result.get("download", {}).get("files", [])),
            "technical_summary_id": result.get("technical_summary_id"),
            "benchmarks": {
                ticker: item.get("technical_summary_id")
                for ticker, item in (result.get("benchmarks") or {}).items()
            },
        }
    if job_type == "historical_earnings":
        return {
            "qc_rows": result.get("qc_row_count", 0),
            "events": len(result.get("historical_earnings_event_ids", [])),
        }
    if job_type == "historical_option_chain":
        return {
            "files": len(result.get("files", [])),
            "manifests": len(result.get("option_chain_download_ids", [])),
        }
    return {}


def equity_price_windows(report_date: date) -> dict[str, date]:
    daily_start = report_date - timedelta(days=365 * 3)
    daily_end = add_trading_days(report_date, 2)
    minute_start = add_trading_days(report_date, -20)
    minute_end = add_trading_days(report_date, 2)
    return {
        "daily_start": daily_start,
        "daily_end": daily_end,
        "minute_start": minute_start,
        "minute_end": minute_end,
    }


def option_chain_window(report_date: date) -> dict[str, date]:
    return {
        "start": add_trading_days(report_date, -5),
        "end": add_trading_days(report_date, 2),
    }


def _run_historical_option_chain(db, job: DataJob, ticker: str) -> dict[str, Any]:
    params = job.params or {}
    report_date = _parse_day(params.get("report_date"))
    window = option_chain_window(report_date)
    min_dte = int(params.get("min_dte", 0))
    max_dte = int(params.get("max_dte", 180))
    min_strike_rank = int(params.get("min_strike_rank", -250))
    max_strike_rank = int(params.get("max_strike_rank", 250))
    paths = download_option_chain(
        ticker=ticker,
        start=window["start"],
        end=window["end"],
        min_dte=min_dte,
        max_dte=max_dte,
        min_strike_rank=min_strike_rank,
        max_strike_rank=max_strike_rank,
    )
    download_ids = []
    for path in paths:
        trade_date = _parse_day(path.stem)
        record = _upsert_option_chain_manifest(
            db,
            ticker=ticker,
            report_date=report_date,
            trade_date=trade_date,
            path=path,
            min_dte=min_dte,
            max_dte=max_dte,
            min_strike_rank=min_strike_rank,
            max_strike_rank=max_strike_rank,
        )
        download_ids.append(record.id)
    summary_id = _build_and_upsert_option_summary(db, ticker, report_date, paths)
    return {
        "ticker": ticker,
        "window": {key: value.isoformat() for key, value in window.items()},
        "report_date": report_date.isoformat(),
        "filter_preset": "earnings_wide_v1",
        "min_dte": min_dte,
        "max_dte": max_dte,
        "min_strike_rank": min_strike_rank,
        "max_strike_rank": max_strike_rank,
        "files": [str(path) for path in paths],
        "option_chain_download_ids": download_ids,
        "option_chain_summary_id": summary_id,
    }


def add_trading_days(anchor: date, offset: int) -> date:
    if offset == 0:
        return anchor
    days = abs(offset)
    padding = max(10, days * 3 + 10)
    if offset > 0:
        schedule = NYSE.schedule(start_date=anchor, end_date=anchor + timedelta(days=padding))
        trading_days = [ts.date() for ts in schedule.index if ts.date() > anchor]
        return trading_days[days - 1]
    schedule = NYSE.schedule(start_date=anchor - timedelta(days=padding), end_date=anchor)
    trading_days = [ts.date() for ts in schedule.index if ts.date() < anchor]
    return trading_days[-days]


def _claim_next_job(job_type: str) -> DataJob | None:
    db = SessionLocal()
    try:
        job = (
            db.query(DataJob)
            .filter(DataJob.job_type == job_type, DataJob.status == "pending")
            .order_by(DataJob.priority.asc(), DataJob.created_at.asc(), DataJob.id.asc())
            .first()
        )
        if job is None:
            return None
        job.status = "running"
        job.started_at = func.now()
        db.commit()
        job_id = job.id
    finally:
        db.close()

    db = SessionLocal()
    try:
        return db.query(DataJob).filter(DataJob.id == job_id).first()
    finally:
        db.expunge_all()
        db.close()


def _record_equity_downloads(
    db,
    ticker: str,
    report_date: date,
    windows: dict[str, date],
    result: dict[str, Any],
) -> None:
    window_id = f"earnings_{report_date.strftime('%Y%m%d')}"
    files = result.get("files", [])
    daily_files = [item for item in files if item.get("resolution") == "daily"]
    minute_files = [item for item in files if item.get("resolution") == "minute"]
    for item in daily_files:
        _upsert_manifest(
            db,
            ticker=ticker,
            resolution="daily",
            window_id=window_id,
            start_date=windows["daily_start"],
            end_date=windows["daily_end"],
            item=item,
        )
    for item in minute_files:
        trade_date = _parse_day(item.get("trade_date"))
        _upsert_manifest(
            db,
            ticker=ticker,
            resolution="minute",
            window_id=window_id,
            start_date=trade_date,
            end_date=trade_date,
            item=item,
        )


def _ensure_benchmark_summaries(
    db,
    report_date: date,
    windows: dict[str, date],
    *,
    exclude: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    excluded = {ticker.upper() for ticker in (exclude or set())}
    results = {}
    for benchmark in BENCHMARK_TICKERS:
        if benchmark in excluded:
            continue
        results[benchmark] = _ensure_equity_summary(db, benchmark, report_date, windows)
    return results


def _ensure_equity_summary(
    db,
    ticker: str,
    report_date: date,
    windows: dict[str, date],
) -> dict[str, Any]:
    window_id = f"earnings_{report_date.strftime('%Y%m%d')}"
    existing = _latest_technical_summary(db, ticker, window_id)
    if existing is not None:
        return {
            "technical_summary_id": existing.id,
            "status": "existing_summary",
            "as_of_date": existing.as_of_date.isoformat(),
        }

    try:
        summary = build_technical_summary(ticker=ticker, report_date=report_date, windows=windows)
        summary_id = _upsert_technical_summary(db, summary, windows)
        return {
            "technical_summary_id": summary_id,
            "status": "built_from_existing_parquet",
            "as_of_date": summary["as_of_date"],
        }
    except ValueError:
        download_result = download_equity_prices(ticker=ticker, **windows)
        _record_equity_downloads(db, ticker, report_date, windows, download_result)
        summary = build_technical_summary(ticker=ticker, report_date=report_date, windows=windows)
        summary_id = _upsert_technical_summary(db, summary, windows)
        return {
            "technical_summary_id": summary_id,
            "status": "downloaded",
            "as_of_date": summary["as_of_date"],
            "files": len(download_result.get("files", [])),
        }


def _latest_technical_summary(db, ticker: str, window_id: str) -> EquityTechnicalSummary | None:
    return (
        db.query(EquityTechnicalSummary)
        .filter(
            EquityTechnicalSummary.ticker == ticker,
            EquityTechnicalSummary.window_id == window_id,
        )
        .order_by(EquityTechnicalSummary.as_of_date.desc(), EquityTechnicalSummary.id.desc())
        .first()
    )


def _upsert_technical_summary(db, summary: dict[str, Any], windows: dict[str, date]) -> int:
    daily = summary["daily"]
    minute = summary.get("minute", {})
    latest_minute = minute.get("latest_day") or {}
    regimes = summary["regimes"]
    ticker = summary["ticker"]
    window_id = summary["window_id"]
    as_of_date = _parse_day(summary["as_of_date"])
    report_date = _parse_day(summary["report_date"])
    existing = (
        db.query(EquityTechnicalSummary)
        .filter(
            EquityTechnicalSummary.ticker == ticker,
            EquityTechnicalSummary.window_id == window_id,
            EquityTechnicalSummary.as_of_date == as_of_date,
        )
        .first()
    )
    if existing is None:
        existing = EquityTechnicalSummary(
            ticker=ticker,
            window_id=window_id,
            as_of_date=as_of_date,
            report_date=report_date,
        )
        db.add(existing)

    existing.daily_start_date = windows["daily_start"]
    existing.daily_end_date = windows["daily_end"]
    existing.minute_start_date = windows["minute_start"]
    existing.minute_end_date = windows["minute_end"]
    existing.trend_regime = regimes.get("trend_regime")
    existing.momentum_regime = regimes.get("momentum_regime")
    existing.volatility_regime = regimes.get("volatility_regime")
    existing.volume_regime = regimes.get("volume_regime")
    existing.close_price = daily.get("close")
    existing.return_5d_pct = daily.get("return_5d_pct")
    existing.return_20d_pct = daily.get("return_20d_pct")
    existing.return_60d_pct = daily.get("return_60d_pct")
    existing.rsi_14 = daily.get("rsi_14")
    existing.atr_14_pct = daily.get("atr_14_pct")
    existing.hv_20 = daily.get("hv_20")
    existing.hv_60 = daily.get("hv_60")
    existing.distance_to_52w_high_pct = daily.get("distance_to_52w_high_pct")
    existing.distance_to_52w_low_pct = daily.get("distance_to_52w_low_pct")
    existing.above_sma_20 = daily.get("above_sma_20")
    existing.above_sma_50 = daily.get("above_sma_50")
    existing.above_sma_200 = daily.get("above_sma_200")
    existing.latest_close_vs_vwap_pct = latest_minute.get("close_vs_vwap_pct")
    existing.summary_json = summary
    db.flush()
    return existing.id


def _upsert_historical_earnings_event(db, ticker: str, row: dict[str, Any]) -> HistoricalEarningsEvent | None:
    qc_observed_date = _parse_optional_day(row.get("observed_date"))
    qc_file_date = _parse_optional_day(row.get("file_date"))
    period_ending_date = _parse_optional_day(row.get("period_ending_date"))
    report_date = _historical_earnings_anchor_date(qc_file_date, qc_observed_date, period_ending_date)
    if report_date is None:
        return None
    sec = enrich_earnings_anchor(ticker, report_date)
    existing = (
        db.query(HistoricalEarningsEvent)
        .filter(
            HistoricalEarningsEvent.ticker == ticker,
            HistoricalEarningsEvent.report_date == report_date,
            HistoricalEarningsEvent.period_ending_date == period_ending_date,
        )
        .first()
    )
    if existing is None:
        existing = HistoricalEarningsEvent(
            ticker=ticker,
            report_date=report_date,
            period_ending_date=period_ending_date,
        )
        db.add(existing)
    existing.qc_observed_date = qc_observed_date
    existing.qc_file_date = qc_file_date
    existing.basic_eps_3m = _decimal_or_none(row.get("basic_eps_3m"))
    existing.diluted_eps_3m = _decimal_or_none(row.get("diluted_eps_3m"))
    existing.sec_cik = sec.get("sec_cik")
    existing.sec_acceptance_datetime = parse_acceptance_datetime(sec.get("sec_acceptance_datetime"))
    existing.sec_form_type = sec.get("sec_form_type")
    existing.sec_accession_number = sec.get("sec_accession_number")
    existing.sec_primary_document = sec.get("sec_primary_document")
    existing.sec_items = sec.get("sec_items")
    existing.release_session = sec.get("release_session") or "unknown"
    existing.release_time_confidence = sec.get("release_time_confidence") or "low"
    existing.source_url = sec.get("source_url")
    existing.source_payload = {"qc": row, "sec": sec}
    existing.notes = f"{sec.get('sec_match_status')}; anchor={_anchor_note(qc_file_date, qc_observed_date, period_ending_date)}"
    db.flush()
    return existing


def _historical_earnings_anchor_date(
    qc_file_date: date | None,
    qc_observed_date: date | None,
    period_ending_date: date | None,
) -> date | None:
    if qc_file_date and period_ending_date and qc_file_date < period_ending_date:
        return qc_observed_date or qc_file_date
    return qc_file_date or qc_observed_date


def _anchor_note(qc_file_date: date | None, qc_observed_date: date | None, period_ending_date: date | None) -> str:
    if qc_file_date and period_ending_date and qc_file_date < period_ending_date:
        return "observed_date_used_due_to_stale_file_date"
    if qc_file_date:
        return "file_date"
    if qc_observed_date:
        return "observed_date"
    return "unknown"


def _upsert_manifest(
    db,
    *,
    ticker: str,
    resolution: str,
    window_id: str,
    start_date: date,
    end_date: date,
    item: dict[str, Any],
) -> None:
    existing = (
        db.query(EquityPriceDownload)
        .filter(
            EquityPriceDownload.ticker == ticker,
            EquityPriceDownload.resolution == resolution,
            EquityPriceDownload.window_id == window_id,
            EquityPriceDownload.start_date == start_date,
            EquityPriceDownload.end_date == end_date,
        )
        .first()
    )
    if existing is None:
        existing = EquityPriceDownload(
            ticker=ticker,
            resolution=resolution,
            window_id=window_id,
            start_date=start_date,
            end_date=end_date,
        )
        db.add(existing)
    existing.path = item.get("path")
    existing.row_count = item.get("row_count")
    existing.file_size = item.get("file_size")
    existing.status = "success"
    existing.error_message = None
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise


def _upsert_option_chain_manifest(
    db,
    *,
    ticker: str,
    report_date: date,
    trade_date: date,
    path,
    min_dte: int,
    max_dte: int,
    min_strike_rank: int,
    max_strike_rank: int,
) -> OptionChainDownload:
    window_id = f"earnings_{report_date.strftime('%Y%m%d')}"
    stats = _option_parquet_stats(path)
    existing = (
        db.query(OptionChainDownload)
        .filter(
            OptionChainDownload.ticker == ticker,
            OptionChainDownload.trade_date == trade_date,
            OptionChainDownload.filter_preset == "earnings_wide_v1",
            OptionChainDownload.min_dte == min_dte,
            OptionChainDownload.max_dte == max_dte,
            OptionChainDownload.min_strike_rank == min_strike_rank,
            OptionChainDownload.max_strike_rank == max_strike_rank,
        )
        .first()
    )
    if existing is None:
        existing = OptionChainDownload(
            ticker=ticker,
            trade_date=trade_date,
            filter_preset="earnings_wide_v1",
            min_dte=min_dte,
            max_dte=max_dte,
            min_strike_rank=min_strike_rank,
            max_strike_rank=max_strike_rank,
        )
        db.add(existing)
    existing.window_id = window_id
    existing.resolution = "minute"
    existing.path = str(path)
    existing.contract_count = stats["contract_count"]
    existing.row_count = stats["row_count"]
    existing.file_size = stats["file_size"]
    existing.status = "success"
    existing.error_message = None
    db.flush()
    return existing


def _build_and_upsert_option_summary(db, ticker: str, report_date: date, paths: list) -> int | None:
    if not paths:
        return None
    window_id = f"earnings_{report_date.strftime('%Y%m%d')}"
    technical = _latest_technical_summary(db, ticker, window_id)
    if technical is None or technical.close_price is None:
        raise ValueError(f"Cannot build option summary for {ticker}: missing equity technical spot price")
    summary = build_option_chain_summary(
        ticker=ticker,
        report_date=report_date,
        spot_price=float(technical.close_price),
        option_paths=paths,
    )
    existing = (
        db.query(OptionChainSummary)
        .filter(
            OptionChainSummary.ticker == ticker,
            OptionChainSummary.window_id == window_id,
            OptionChainSummary.as_of_date == _parse_day(summary["as_of_date"]),
        )
        .first()
    )
    if existing is None:
        existing = OptionChainSummary(
            ticker=ticker,
            window_id=window_id,
            report_date=report_date,
            as_of_date=_parse_day(summary["as_of_date"]),
        )
        db.add(existing)
    existing.spot_price = summary.get("spot_price")
    existing.front_expiry = _parse_optional_day(summary.get("front_expiry"))
    existing.days_to_expiry = summary.get("days_to_expiry")
    existing.atm_strike = summary.get("atm_strike")
    existing.atm_call_mid = summary.get("atm_call_mid")
    existing.atm_put_mid = summary.get("atm_put_mid")
    existing.atm_straddle_mid = summary.get("atm_straddle_mid")
    existing.implied_move_pct = summary.get("implied_move_pct")
    existing.median_spread_pct = summary.get("median_spread_pct")
    existing.atm_spread_pct = summary.get("atm_spread_pct")
    existing.total_call_volume = summary.get("total_call_volume")
    existing.total_put_volume = summary.get("total_put_volume")
    existing.call_put_volume_ratio = summary.get("call_put_volume_ratio")
    existing.liquidity_score = summary.get("liquidity_score")
    existing.volatility_pricing_score = summary.get("volatility_pricing_score")
    existing.directional_skew_score = summary.get("directional_skew_score")
    existing.summary_json = summary
    db.flush()
    return existing.id


def _option_parquet_stats(path) -> dict[str, int]:
    import pyarrow.parquet as pq

    table = pq.read_table(path, columns=["symbol"])
    symbols = table.column("symbol").to_pylist()
    return {
        "contract_count": len(set(symbols)),
        "row_count": len(symbols),
        "file_size": path.stat().st_size,
    }


def _parse_day(value: str | date | None) -> date:
    if isinstance(value, date):
        return value
    if not value:
        raise ValueError("Date value is required")
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return datetime.strptime(text, "%Y-%m-%d").date()
    raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD or YYYYMMDD.")


def _parse_optional_day(value: str | date | None) -> date | None:
    if not value:
        return None
    return _parse_day(value)


def _decimal_or_none(value: Any):
    from decimal import Decimal, InvalidOperation

    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
