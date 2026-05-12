"""Small link-formatting helpers shared by bot and scraper code."""

from __future__ import annotations

import html


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
