"""Build compact news summaries for earnings-options LLM input."""

from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func

from utils.db import EarningsNewsSummary, SessionLocal

DEFAULT_MAX_ARTICLES = 12
MARKET_TERMS = {
    "market",
    "markets",
    "futures",
    "s&p",
    "nasdaq",
    "dow",
    "fed",
    "rate",
    "rates",
    "inflation",
    "oil",
    "dollar",
    "yields",
    "treasury",
    "stocks",
}
POSITIVE_TERMS = {
    "beat",
    "beats",
    "growth",
    "raises",
    "raised",
    "strong",
    "record",
    "upgrade",
    "surge",
    "jumps",
    "tops",
}
NEGATIVE_TERMS = {
    "miss",
    "misses",
    "cut",
    "cuts",
    "weak",
    "lawsuit",
    "probe",
    "downgrade",
    "falls",
    "drops",
    "risk",
    "risks",
}
STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "amid",
    "before",
    "from",
    "into",
    "over",
    "that",
    "their",
    "this",
    "with",
    "will",
    "your",
    "stock",
    "stocks",
    "market",
    "markets",
    "news",
}


def build_news_summary_from_csvs(
    *,
    ticker: str,
    report_date: date,
    paths: list[str | Path],
    company_name: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    ticker = ticker.upper()
    rows = []
    for path in paths:
        rows.extend(_read_csv(Path(path)))
    if not rows:
        raise ValueError("No news rows available")

    normalized = [_normalize_row(row, ticker, company_name) for row in rows]
    normalized = [row for row in normalized if row["title"] or row["description"]]
    if not normalized:
        raise ValueError("No usable news rows available")

    layers = {
        "company_news": [row for row in normalized if row["layer"] == "company_news"],
        "industry_news": [row for row in normalized if row["layer"] == "industry_news"],
        "market_news": [row for row in normalized if row["layer"] == "market_news"],
    }
    all_dates = [row["date"] for row in normalized if row["date"]]
    summary = {
        "ticker": ticker,
        "window_id": f"earnings_{report_date.strftime('%Y%m%d')}",
        "report_date": report_date.isoformat(),
        "source": "quantconnect",
        "provider": provider or _first_provider(normalized),
        "start_date": min(all_dates).isoformat() if all_dates else None,
        "end_date": max(all_dates).isoformat() if all_dates else None,
        "company_article_count": len(layers["company_news"]),
        "industry_article_count": len(layers["industry_news"]),
        "market_article_count": len(layers["market_news"]),
        "company_news": _layer_summary(layers["company_news"]),
        "industry_news": _layer_summary(layers["industry_news"]),
        "market_news": _layer_summary(layers["market_news"]),
        "overall": {
            "article_count": len(normalized),
            "top_keywords": _top_keywords(normalized),
            "sentiment_proxy": _sentiment_proxy(normalized),
            "notes": [
                "News summary is deterministic and uses title/description heuristics.",
                "It is intended as compact LLM context, not as a full news NLP model.",
            ],
        },
    }
    return summary


def upsert_news_summary(summary: dict[str, Any]) -> int:
    db = SessionLocal()
    try:
        ticker = summary["ticker"].upper()
        window_id = summary["window_id"]
        provider = summary.get("provider") or "unknown"
        existing = (
            db.query(EarningsNewsSummary)
            .filter(
                EarningsNewsSummary.ticker == ticker,
                EarningsNewsSummary.window_id == window_id,
                EarningsNewsSummary.source == summary.get("source", "quantconnect"),
                EarningsNewsSummary.provider == provider,
            )
            .first()
        )
        if existing is None:
            existing = EarningsNewsSummary(
                ticker=ticker,
                window_id=window_id,
                report_date=_parse_day(summary["report_date"]),
                source=summary.get("source", "quantconnect"),
                provider=provider,
            )
            db.add(existing)
        existing.report_date = _parse_day(summary["report_date"])
        existing.start_date = _parse_optional_day(summary.get("start_date"))
        existing.end_date = _parse_optional_day(summary.get("end_date"))
        existing.company_article_count = int(summary.get("company_article_count") or 0)
        existing.industry_article_count = int(summary.get("industry_article_count") or 0)
        existing.market_article_count = int(summary.get("market_article_count") or 0)
        existing.summary_json = summary
        existing.updated_at = func.now()
        db.flush()
        db.commit()
        return existing.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _normalize_row(row: dict[str, Any], ticker: str, company_name: str | None) -> dict[str, Any]:
    title = (row.get("title") or "").strip()
    description = (row.get("description") or "").strip()
    text = f"{title} {description}"
    timestamp = _parse_datetime(row.get("time"))
    return {
        "provider": (row.get("provider") or "").strip() or None,
        "time": timestamp.isoformat() if timestamp else row.get("time"),
        "date": timestamp.date() if timestamp else None,
        "title": title,
        "description": description,
        "url": (row.get("url") or "").strip() or None,
        "layer": _classify_layer(text, ticker, company_name),
        "sentiment": _sentiment_label(text),
    }


def _classify_layer(text: str, ticker: str, company_name: str | None) -> str:
    lower = text.lower()
    name_tokens = [token for token in re.split(r"\W+", (company_name or "").lower()) if len(token) >= 4]
    if ticker.lower() in lower or any(token in lower for token in name_tokens[:3]):
        return "company_news"
    if any(term in lower for term in MARKET_TERMS):
        return "market_news"
    return "industry_news"


def _layer_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(rows, key=_article_rank, reverse=True)
    return {
        "article_count": len(rows),
        "sentiment_proxy": _sentiment_proxy(rows),
        "top_keywords": _top_keywords(rows),
        "key_articles": [
            {
                "time": row["time"],
                "title": row["title"],
                "description": row["description"][:500] if row["description"] else "",
                "url": row["url"],
                "sentiment": row["sentiment"],
            }
            for row in ranked[:DEFAULT_MAX_ARTICLES]
        ],
    }


def _article_rank(row: dict[str, Any]) -> int:
    text = f"{row['title']} {row['description']}".lower()
    score = 0
    for term in ("earnings", "guidance", "revenue", "margin", "forecast", "analyst", "upgrade", "downgrade"):
        if term in text:
            score += 2
    if row["description"]:
        score += 1
    if row["url"]:
        score += 1
    return score


def _top_keywords(rows: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    counter = Counter()
    for row in rows:
        text = f"{row['title']} {row['description']}".lower()
        for token in re.findall(r"[a-z][a-z0-9]{2,}", text):
            if token not in STOPWORDS:
                counter[token] += 1
    return [{"term": term, "count": count} for term, count in counter.most_common(limit)]


def _sentiment_proxy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row.get("sentiment") or "neutral" for row in rows)
    return {
        "positive": counts.get("positive", 0),
        "negative": counts.get("negative", 0),
        "neutral": counts.get("neutral", 0),
    }


def _sentiment_label(text: str) -> str:
    lower = text.lower()
    positive = sum(1 for term in POSITIVE_TERMS if term in lower)
    negative = sum(1 for term in NEGATIVE_TERMS if term in lower)
    if positive > negative:
        return "positive"
    if negative > positive:
        return "negative"
    return "neutral"


def _first_provider(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("provider"):
            return row["provider"]
    return "unknown"


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_day(value: str | date) -> date:
    if isinstance(value, date):
        return value
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return datetime.strptime(text[:10], "%Y-%m-%d").date()


def _parse_optional_day(value: Any) -> date | None:
    if not value:
        return None
    return _parse_day(value)
