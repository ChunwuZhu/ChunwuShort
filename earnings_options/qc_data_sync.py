"""QuantConnect earnings/fundamental sync into local business tables."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import func

from qc.earnings_calendar import default_end, default_run_date, normalize_date
from qc.earnings_fundamentals_sync import download_earnings_and_fundamentals
from utils.db import (
    DataJob,
    EarningsWatchlist,
    QCEarningsCurrentEvent,
    QCEarningsEventChange,
    QCEarningsRawEvent,
    QCEarningsSyncRun,
    QCFundamentalSnapshot,
    SessionLocal,
)

MARKET_CAP_MIN = Decimal("10000000000")
DEFAULT_LOOKAHEAD_DAYS = 60


def sync_from_quantconnect(
    *,
    run_date: str | date | None = None,
    start: str | date | None = None,
    end: str | date | None = None,
    days: int = DEFAULT_LOOKAHEAD_DAYS,
    max_events: int = 10000,
) -> dict[str, Any]:
    run_date_text = normalize_date(run_date) if run_date else default_run_date()
    start_text = normalize_date(start) if start else run_date_text
    end_text = normalize_date(end) if end else default_end(start_text, days)

    earnings_rows, fundamental_rows = download_earnings_and_fundamentals(
        run_date=run_date_text,
        start=start_text,
        end=end_text,
        days=days,
        max_events=max_events,
        save_outputs=True,
    )
    return sync_rows(
        earnings_rows=earnings_rows,
        fundamental_rows=fundamental_rows,
        run_date=run_date_text,
        requested_start=start_text,
        requested_end=end_text,
    )


def sync_from_files(
    *,
    earnings_json: Path,
    fundamentals_json: Path,
    run_date: str | date,
    requested_start: str | date,
    requested_end: str | date,
) -> dict[str, Any]:
    earnings_rows = json.loads(earnings_json.read_text(encoding="utf-8"))
    fundamental_rows = json.loads(fundamentals_json.read_text(encoding="utf-8"))
    return sync_rows(
        earnings_rows=earnings_rows,
        fundamental_rows=fundamental_rows,
        run_date=run_date,
        requested_start=requested_start,
        requested_end=requested_end,
    )


def sync_rows(
    *,
    earnings_rows: list[dict[str, Any]],
    fundamental_rows: list[dict[str, Any]],
    run_date: str | date,
    requested_start: str | date,
    requested_end: str | date,
) -> dict[str, Any]:
    run_day = _parse_day(run_date)
    start_day = _parse_day(requested_start)
    end_day = _parse_day(requested_end)
    fundamentals = {row.get("ticker", "").upper(): row for row in fundamental_rows if row.get("ticker")}

    db = SessionLocal()
    sync_run = QCEarningsSyncRun(
        run_date=run_day,
        requested_start_date=start_day,
        requested_end_date=end_day,
        status="running",
    )
    db.add(sync_run)
    db.flush()

    try:
        seen_tickers: set[str] = set()
        eligible_count = 0
        snapshot_ids: dict[str, int] = {}

        for row in earnings_rows:
            ticker = (row.get("ticker") or "").upper()
            if not ticker:
                continue
            report_day = _parse_day(row.get("report_date"))
            report_time = row.get("report_time") or None
            eps_estimate = _decimal(row.get("estimate") or row.get("eps_estimate"))
            raw_event = QCEarningsRawEvent(
                sync_run_id=sync_run.id,
                as_of_date=_parse_day(row.get("as_of_date") or run_day),
                ticker=ticker,
                report_date=report_day,
                report_time=report_time,
                eps_estimate=eps_estimate,
                source_payload=row,
            )
            db.add(raw_event)
            seen_tickers.add(ticker)

        for row in fundamental_rows:
            ticker = (row.get("ticker") or "").upper()
            if not ticker:
                continue
            snapshot = _snapshot_from_row(sync_run.id, run_day, row)
            db.add(snapshot)
            db.flush()
            snapshot_ids[ticker] = snapshot.id

        for row in earnings_rows:
            ticker = (row.get("ticker") or "").upper()
            if not ticker:
                continue
            report_day = _parse_day(row.get("report_date"))
            fundamental = fundamentals.get(ticker, {})
            market_cap = _decimal(fundamental.get("market_cap"))
            is_eligible, reason = _eligibility(market_cap, report_day, run_day)
            if is_eligible:
                eligible_count += 1
            current = (
                db.query(QCEarningsCurrentEvent)
                .filter(QCEarningsCurrentEvent.ticker == ticker, QCEarningsCurrentEvent.is_active.is_(True))
                .order_by(QCEarningsCurrentEvent.id.desc())
                .first()
            )
            values = {
                "company_name": _empty_to_none(fundamental.get("company_name")),
                "report_date": report_day,
                "report_time": row.get("report_time") or None,
                "eps_estimate": _decimal(row.get("estimate") or row.get("eps_estimate")),
                "market_cap": market_cap,
                "exchange_id": _empty_to_none(fundamental.get("exchange_id")),
                "sector_code": _empty_to_none(fundamental.get("sector_code")),
                "industry_code": _empty_to_none(fundamental.get("industry_code")),
                "is_eligible": is_eligible,
                "eligibility_reason": reason,
            }
            if current is None:
                current = QCEarningsCurrentEvent(
                    ticker=ticker,
                    last_sync_run_id=sync_run.id,
                    **values,
                )
                db.add(current)
                db.flush()
            else:
                _record_changes(db, current, values, sync_run.id)
                for key, value in values.items():
                    setattr(current, key, value)
                current.last_seen_at = func.now()
                current.last_sync_run_id = sync_run.id
                current.seen_count = (current.seen_count or 0) + 1
                current.missing_count = 0
            _ensure_watchlist(db, current, snapshot_ids.get(ticker), reason)

        active_events = (
            db.query(QCEarningsCurrentEvent)
            .filter(QCEarningsCurrentEvent.is_active.is_(True))
            .all()
        )
        for event in active_events:
            if event.ticker in seen_tickers:
                continue
            event.missing_count = (event.missing_count or 0) + 1
            event.last_sync_run_id = sync_run.id
            if event.report_date < start_day:
                event.is_active = False
                event.inactive_reason = "expired"
            elif event.missing_count >= 3:
                event.is_active = False
                event.inactive_reason = "missing_from_source"

        sync_run.finished_at = func.now()
        sync_run.status = "success"
        sync_run.raw_event_count = len(earnings_rows)
        sync_run.fundamental_count = len(fundamental_rows)
        sync_run.eligible_count = eligible_count
        db.commit()
        return {
            "sync_run_id": sync_run.id,
            "raw_event_count": len(earnings_rows),
            "fundamental_count": len(fundamental_rows),
            "eligible_count": eligible_count,
            "seen_ticker_count": len(seen_tickers),
        }
    except Exception as exc:
        db.rollback()
        sync_run.status = "failed"
        sync_run.error_message = str(exc)
        sync_run.finished_at = func.now()
        db.add(sync_run)
        db.commit()
        raise
    finally:
        db.close()


def _record_changes(db, current: QCEarningsCurrentEvent, values: dict[str, Any], sync_run_id: int) -> None:
    for key, new_value in values.items():
        old_value = getattr(current, key)
        if str(old_value or "") == str(new_value or ""):
            continue
        db.add(
            QCEarningsEventChange(
                current_event_id=current.id,
                ticker=current.ticker,
                field_name=key,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
                sync_run_id=sync_run_id,
            )
        )


def _ensure_watchlist(
    db,
    current: QCEarningsCurrentEvent,
    snapshot_id: int | None,
    eligibility_reason: str,
) -> None:
    if not current.is_eligible:
        return
    existing = (
        db.query(EarningsWatchlist)
        .filter(EarningsWatchlist.current_event_id == current.id, EarningsWatchlist.status == "watching")
        .first()
    )
    if existing:
        existing.report_date = current.report_date
        existing.report_time = current.report_time
        existing.market_cap = current.market_cap
        existing.last_fundamental_snapshot_id = snapshot_id or existing.last_fundamental_snapshot_id
        return

    watch = EarningsWatchlist(
        current_event_id=current.id,
        ticker=current.ticker,
        status="watching",
        selected_reason=eligibility_reason,
        analysis_start_date=current.report_date - timedelta(days=7),
        report_date=current.report_date,
        report_time=current.report_time,
        market_cap=current.market_cap,
        last_fundamental_snapshot_id=snapshot_id,
    )
    db.add(watch)
    db.flush()
    for job_type in (
        "historical_earnings",
        "historical_company_news",
        "historical_market_news",
        "historical_industry_news",
        "historical_equity_prices",
        "historical_option_chain",
    ):
        db.add(
            DataJob(
                job_type=job_type,
                ticker=current.ticker,
                status="pending",
                params={
                    "watchlist_id": watch.id,
                    "current_event_id": current.id,
                    "report_date": current.report_date.isoformat(),
                },
            )
        )


def _snapshot_from_row(sync_run_id: int, run_day: date, row: dict[str, Any]) -> QCFundamentalSnapshot:
    return QCFundamentalSnapshot(
        sync_run_id=sync_run_id,
        ticker=row.get("ticker", "").upper(),
        snapshot_date=run_day,
        company_name=_empty_to_none(row.get("company_name")),
        market_cap=_decimal(row.get("market_cap")),
        sector_code=_empty_to_none(row.get("sector_code")),
        industry_group_code=_empty_to_none(row.get("industry_group_code")),
        industry_code=_empty_to_none(row.get("industry_code")),
        exchange_id=_empty_to_none(row.get("exchange_id")),
        country_id=_empty_to_none(row.get("country_id")),
        currency_id=_empty_to_none(row.get("currency_id")),
        shares_outstanding=_decimal(row.get("shares_outstanding")),
        revenue_ttm=_decimal(row.get("revenue_ttm")),
        gross_profit_ttm=_decimal(row.get("gross_profit_ttm")),
        operating_income_ttm=_decimal(row.get("operating_income_ttm")),
        net_income_ttm=_decimal(row.get("net_income_ttm")),
        eps_ttm=_decimal(row.get("eps_ttm")),
        pe_ratio=_decimal(row.get("pe_ratio")),
        forward_pe_ratio=_decimal(row.get("forward_pe_ratio")),
        pb_ratio=_decimal(row.get("pb_ratio")),
        ps_ratio=_decimal(row.get("ps_ratio")),
        pcf_ratio=_decimal(row.get("pcf_ratio")),
        ev_to_ebitda=_decimal(row.get("ev_to_ebitda")),
        ev_to_revenue=_decimal(row.get("ev_to_revenue")),
        roe=_decimal(row.get("roe")),
        roa=_decimal(row.get("roa")),
        current_ratio=_decimal(row.get("current_ratio")),
        quick_ratio=_decimal(row.get("quick_ratio")),
        gross_margin=_decimal(row.get("gross_margin")),
        net_margin=_decimal(row.get("net_margin")),
        fundamental_json=row,
    )


def _eligibility(market_cap: Decimal | None, report_day: date, run_day: date) -> tuple[bool, str]:
    if report_day < run_day:
        return False, "expired"
    if market_cap is None:
        return False, "missing_market_cap"
    if market_cap < MARKET_CAP_MIN:
        return False, "market_cap_below_10b"
    return True, "market_cap_gte_10b"


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


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _empty_to_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
