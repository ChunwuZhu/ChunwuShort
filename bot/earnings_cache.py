"""Database cache for earnings calendar data."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError

from bot.earnings import TIME_ORDER, fetch_earnings, today_ct
from utils.db import Base, EarningsCacheDate, EarningsEvent, SessionLocal, engine

log = logging.getLogger(__name__)


def ensure_earnings_table() -> None:
    Base.metadata.create_all(bind=engine, tables=[EarningsEvent.__table__, EarningsCacheDate.__table__])


def _trading_dates(start: date, end: date) -> list[date]:
    try:
        import pandas_market_calendars as mcal

        nyse = mcal.get_calendar("NYSE")
        schedule = nyse.schedule(start_date=start, end_date=end)
        return [idx.date() for idx in schedule.index]
    except Exception as exc:
        log.warning("[EARNINGS] NYSE calendar unavailable for cache window: %s", exc)
        result = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                result.append(current)
            current += timedelta(days=1)
        return result


def get_cached_earnings(target: date) -> list[dict]:
    db = SessionLocal()
    try:
        rows = (
            db.query(EarningsEvent)
            .filter(EarningsEvent.report_date == target)
            .order_by(EarningsEvent.report_time.asc(), EarningsEvent.market_cap.desc().nullslast(), EarningsEvent.ticker.asc())
            .all()
        )
        result = [
            {
                "ticker": row.ticker,
                "exchange": row.exchange,
                "time": row.report_time or "",
                "market_cap": float(row.market_cap or 0),
                "cap_str": row.cap_str,
            }
            for row in rows
        ]
        result.sort(key=lambda item: (TIME_ORDER.get(item["time"], 1), -(item["market_cap"] or 0), item["ticker"]))
        return result
    finally:
        db.close()


def is_date_cached(target: date) -> bool:
    db = SessionLocal()
    try:
        return db.query(EarningsCacheDate.id).filter(EarningsCacheDate.report_date == target).first() is not None
    finally:
        db.close()


def mark_date_cached(db, target: date, event_count: int) -> None:
    existing = db.query(EarningsCacheDate).filter(EarningsCacheDate.report_date == target).one_or_none()
    if existing:
        existing.event_count = event_count
    else:
        db.add(EarningsCacheDate(report_date=target, event_count=event_count))


def upsert_earnings(target: date, earnings: list[dict]) -> int:
    db = SessionLocal()
    changed = 0
    try:
        for item in earnings:
            ticker = str(item.get("ticker", "")).strip().upper()
            report_time = str(item.get("time") or "")
            if not ticker:
                continue

            existing = (
                db.query(EarningsEvent)
                .filter(
                    EarningsEvent.report_date == target,
                    EarningsEvent.ticker == ticker,
                    EarningsEvent.report_time == report_time,
                )
                .one_or_none()
            )
            if existing:
                existing.exchange = item.get("exchange")
                existing.market_cap = item.get("market_cap")
                existing.cap_str = item.get("cap_str")
                existing.source = "nasdaq"
                changed += 1
                continue

            db.add(
                EarningsEvent(
                    report_date=target,
                    ticker=ticker,
                    exchange=item.get("exchange"),
                    report_time=report_time,
                    market_cap=item.get("market_cap"),
                    cap_str=item.get("cap_str"),
                    source="nasdaq",
                )
            )
            changed += 1

        mark_date_cached(db, target, len(earnings))
        db.commit()
        return changed
    except IntegrityError:
        db.rollback()
        log.warning("[EARNINGS] duplicate event hit during upsert; retrying as update")
        return upsert_earnings(target, earnings)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def refresh_earnings_date(target: date) -> int:
    earnings = await fetch_earnings(target)
    changed = upsert_earnings(target, earnings)
    log.info("[EARNINGS] cached %s: %d events", target, changed)
    return changed


async def refresh_earnings_window(start: date | None = None, days: int = 14) -> int:
    start = start or today_ct()
    end = start + timedelta(days=days)
    total = 0
    for target in _trading_dates(start, end):
        total += await refresh_earnings_date(target)
    log.info("[EARNINGS] cache window refreshed %s to %s: %d events", start, end, total)
    return total


async def get_or_fetch_earnings(target: date) -> tuple[list[dict], bool]:
    if is_date_cached(target):
        return get_cached_earnings(target), True

    await refresh_earnings_date(target)
    return get_cached_earnings(target), False
