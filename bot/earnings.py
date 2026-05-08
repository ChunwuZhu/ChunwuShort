"""Manual earnings lookup for the unified ShortChunwuBot."""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp

log = logging.getLogger(__name__)

NASDAQ_URL = "https://api.nasdaq.com/api/calendar/earnings"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible)", "Accept": "application/json"}
CAP_SEM = 10
WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
MIN_CAP = 100_000_000_000
TIME_ORDER = {"盘前": 0, "": 1, "盘后": 2}
TG_LIMIT = 4096
CT = ZoneInfo("America/Chicago")

US_HOLIDAYS: set[date] = {
    # 2025
    date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17), date(2025, 4, 18),
    date(2025, 5, 26), date(2025, 6, 19), date(2025, 7, 4), date(2025, 9, 1),
    date(2025, 11, 27), date(2025, 12, 25),
    # 2026
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
    # 2027
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26),
    date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6),
    date(2027, 11, 25), date(2027, 12, 24),
}


def today_ct() -> date:
    return datetime.now(CT).date()


def next_trading_day(from_date: date | None = None) -> date:
    start = from_date or today_ct()
    try:
        import pandas_market_calendars as mcal

        nyse = mcal.get_calendar("NYSE")
        schedule = nyse.schedule(start_date=start + timedelta(days=1), end_date=start + timedelta(days=14))
        if not schedule.empty:
            return schedule.index[0].date()
    except Exception as exc:
        log.warning("[EARNINGS] NYSE calendar unavailable, using fallback holiday list: %s", exc)

    d = start + timedelta(days=1)
    while d.weekday() >= 5 or d in US_HOLIDAYS:
        d += timedelta(days=1)
    return d


def split_message(text: str) -> list[str]:
    if len(text) <= TG_LIMIT:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.split("\n"):
        line_len = len(line) + 1
        if current and current_len + line_len > TG_LIMIT:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len

    if current:
        chunks.append("\n".join(current))
    return chunks


def _fmt_cap(market_cap: float | None) -> str:
    if not market_cap:
        return "N/A"
    if market_cap >= 1e12:
        return f"${market_cap / 1e12:.2f}T"
    if market_cap >= 1e9:
        return f"${market_cap / 1e9:.1f}B"
    return f"${market_cap / 1e6:.0f}M"


def _parse_market_cap(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("$", "").replace(",", "").strip().upper()
    if not cleaned or cleaned in {"N/A", "NA", "-"}:
        return None
    multiplier = 1.0
    if cleaned.endswith("T"):
        multiplier = 1_000_000_000_000.0
        cleaned = cleaned[:-1]
    elif cleaned.endswith("B"):
        multiplier = 1_000_000_000.0
        cleaned = cleaned[:-1]
    elif cleaned.endswith("M"):
        multiplier = 1_000_000.0
        cleaned = cleaned[:-1]
    try:
        return float(cleaned) * multiplier
    except ValueError:
        return None


def _normalize_exchange(exchange: str | None) -> str:
    value = (exchange or "").strip().upper()
    if value in {
        "NASDAQ",
        "NASDAQ-GS",
        "NASDAQ-GM",
        "NASDAQ-CM",
        "NASDAQGS",
        "NASDAQGM",
        "NASDAQCM",
        "NMS",
        "NGS",
        "NGM",
        "NCM",
    }:
        return "NASDAQ"
    if value in {"NYSE", "NEW YORK STOCK EXCHANGE", "NYS", "NYQ"}:
        return "NYSE"
    if value in {"NYSE AMERICAN", "AMEX", "NYSEAMERICAN", "ASE"}:
        return "NYSEAMERICAN"
    return "NASDAQ"


def google_finance_url(ticker: str, exchange: str | None = None) -> str:
    safe_ticker = html.escape(ticker.strip().upper())
    safe_exchange = html.escape(_normalize_exchange(exchange))
    return f"https://www.google.com/finance/quote/{safe_ticker}:{safe_exchange}"


def _exchange_sync(ticker: str) -> str | None:
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).info
        return info.get("exchange") or info.get("fullExchangeName")
    except Exception:
        return None


async def _exchange(ticker: str, sem: asyncio.Semaphore) -> str | None:
    async with sem:
        try:
            return await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(None, _exchange_sync, ticker),
                timeout=10,
            )
        except asyncio.TimeoutError:
            return None


async def fetch_earnings(target_date: date) -> list[dict]:
    raw_rows: list[dict] = []
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                NASDAQ_URL,
                headers=HEADERS,
                params={"date": target_date.strftime("%Y-%m-%d")},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                raw_rows = (await response.json(content_type=None)).get("data", {}).get("rows") or []
    except Exception as exc:
        log.warning("[EARNINGS] nasdaq fetch failed: %s", exc)
        return []

    if not raw_rows:
        return []

    candidates = []
    for row in raw_rows:
        ticker = row.get("symbol", "").strip()
        market_cap = _parse_market_cap(row.get("marketCap"))
        if ticker and (market_cap or 0) >= MIN_CAP:
            candidates.append((row, ticker, market_cap))

    sem = asyncio.Semaphore(CAP_SEM)
    exchanges = await asyncio.gather(*[_exchange(ticker, sem) for _, ticker, _ in candidates])

    result = []
    for (row, ticker, market_cap), exchange in zip(candidates, exchanges):
        report_time = row.get("time", "").lower()
        result.append(
            {
                "ticker": ticker,
                "exchange": exchange,
                "time": "盘前" if "pre" in report_time else "盘后" if "after" in report_time else "",
                "market_cap": market_cap,
                "cap_str": _fmt_cap(market_cap),
            }
        )

    result.sort(key=lambda item: (TIME_ORDER.get(item["time"], 1), -(item["market_cap"] or 0)))
    return result


def format_earnings_message(target_date: date, earnings: list[dict]) -> str:
    weekday = WEEKDAY_ZH[target_date.weekday()]
    if not earnings:
        return f"📅 {target_date} ({weekday}) 无 >$100B 财报"

    lines = [f"📅 {target_date} ({weekday}) 财报 {len(earnings)}"]
    group_labels = {"盘前": "🌅 盘前", "": "🕐 盘中", "盘后": "🌆 盘后"}
    current = None
    for item in earnings:
        if item["time"] != current:
            current = item["time"]
            lines.append(group_labels[current])
        ticker = html.escape(item["ticker"])
        link = google_finance_url(item["ticker"], item.get("exchange"))
        lines.append(f'<a href="{link}">{ticker}</a> {item["cap_str"]}')
    return "\n".join(lines)
