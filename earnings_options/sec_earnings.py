"""SEC EDGAR helpers for historical earnings release timing."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import requests

SEC_HEADERS = {
    "User-Agent": os.getenv("SEC_USER_AGENT", "A02Info earnings research chunwu@example.com"),
    "Accept-Encoding": "gzip, deflate",
}
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
EASTERN = ZoneInfo("America/New_York")


def enrich_earnings_anchor(ticker: str, anchor_date: date, search_days: int = 2) -> dict[str, Any]:
    try:
        cik = ticker_to_cik(ticker)
    except requests.RequestException as exc:
        return {
            "sec_cik": None,
            "sec_match_status": f"sec_request_failed: {exc}",
            "release_session": "unknown",
            "release_time_confidence": "low",
        }
    if not cik:
        return {
            "sec_cik": None,
            "sec_match_status": "missing_cik",
            "release_session": "unknown",
            "release_time_confidence": "low",
        }
    try:
        filings = get_company_filings(cik)
    except requests.RequestException as exc:
        return {
            "sec_cik": cik,
            "sec_match_status": f"sec_request_failed: {exc}",
            "release_session": "unknown",
            "release_time_confidence": "low",
        }
    matched = match_earnings_filing(filings, anchor_date, search_days=search_days)
    if not matched:
        return {
            "sec_cik": cik,
            "sec_match_status": "no_nearby_filing",
            "release_session": "unknown",
            "release_time_confidence": "low",
        }
    accepted = parse_acceptance_datetime(matched.get("acceptanceDateTime"))
    session = release_session(accepted)
    confidence = release_confidence(matched, anchor_date, accepted)
    accession = matched.get("accessionNumber")
    primary_doc = matched.get("primaryDocument")
    source_url = filing_url(cik, accession, primary_doc) if accession and primary_doc else None
    return {
        "sec_cik": cik,
        "sec_match_status": "matched",
        "sec_acceptance_datetime": accepted.isoformat() if accepted else None,
        "sec_form_type": matched.get("form"),
        "sec_accession_number": accession,
        "sec_primary_document": primary_doc,
        "sec_items": matched.get("items"),
        "release_session": session,
        "release_time_confidence": confidence,
        "source_url": source_url,
    }


@lru_cache(maxsize=1)
def ticker_map() -> dict[str, str]:
    response = requests.get(SEC_COMPANY_TICKERS_URL, headers=SEC_HEADERS, timeout=30)
    response.raise_for_status()
    data = response.json()
    mapping = {}
    for item in data.values():
        ticker = str(item.get("ticker", "")).upper()
        cik = str(item.get("cik_str", "")).zfill(10)
        if ticker and cik:
            mapping[ticker] = cik
    return mapping


def ticker_to_cik(ticker: str) -> str | None:
    return ticker_map().get(ticker.upper())


def get_company_filings(cik: str) -> list[dict[str, Any]]:
    response = requests.get(SEC_SUBMISSIONS_URL.format(cik=cik), headers=SEC_HEADERS, timeout=30)
    response.raise_for_status()
    data = response.json()
    filings = flatten_recent(data.get("filings", {}).get("recent", {}))
    for file_info in data.get("filings", {}).get("files", []):
        name = file_info.get("name")
        if not name:
            continue
        url = f"https://data.sec.gov/submissions/{name}"
        file_response = requests.get(url, headers=SEC_HEADERS, timeout=30)
        file_response.raise_for_status()
        filings.extend(flatten_recent(file_response.json()))
    return filings


def flatten_recent(recent: dict[str, list]) -> list[dict[str, Any]]:
    if not recent:
        return []
    keys = list(recent.keys())
    n = max(len(recent.get(key, [])) for key in keys)
    rows = []
    for i in range(n):
        row = {}
        for key in keys:
            values = recent.get(key, [])
            row[key] = values[i] if i < len(values) else None
        rows.append(row)
    return rows


def match_earnings_filing(filings: list[dict[str, Any]], anchor_date: date, search_days: int) -> dict[str, Any] | None:
    start = anchor_date - timedelta(days=search_days)
    end = anchor_date + timedelta(days=search_days)
    candidates = []
    for filing in filings:
        form = filing.get("form")
        if form not in {"8-K", "8-K/A", "10-Q", "10-K", "6-K", "6-K/A"}:
            continue
        filing_date = parse_date(filing.get("filingDate"))
        accepted = parse_acceptance_datetime(filing.get("acceptanceDateTime"))
        event_date = accepted.date() if accepted else filing_date
        if not event_date or event_date < start or event_date > end:
            continue
        candidates.append(filing)
    if not candidates:
        return None

    def score(filing: dict[str, Any]) -> tuple[int, int, str]:
        form = filing.get("form") or ""
        items = str(filing.get("items") or "")
        accepted = parse_acceptance_datetime(filing.get("acceptanceDateTime"))
        event_date = accepted.date() if accepted else parse_date(filing.get("filingDate")) or anchor_date
        item_score = 0 if "2.02" in items else 1
        form_score = {"8-K": 0, "8-K/A": 1, "6-K": 2, "6-K/A": 3, "10-Q": 4, "10-K": 5}.get(form, 9)
        distance = abs((event_date - anchor_date).days)
        return (item_score, form_score + distance * 10, str(filing.get("acceptanceDateTime") or ""))

    return sorted(candidates, key=score)[0]


def release_session(value: datetime | None) -> str:
    if value is None:
        return "unknown"
    local = value.astimezone(EASTERN)
    minutes = local.hour * 60 + local.minute
    if 4 * 60 <= minutes < 9 * 60 + 30:
        return "premarket"
    if 9 * 60 + 30 <= minutes < 16 * 60:
        return "regular"
    if 16 * 60 <= minutes < 20 * 60:
        return "postmarket"
    return "extended"


def release_confidence(filing: dict[str, Any], anchor_date: date, accepted: datetime | None) -> str:
    form = filing.get("form")
    items = str(filing.get("items") or "")
    event_date = accepted.date() if accepted else parse_date(filing.get("filingDate"))
    same_or_near = event_date is not None and abs((event_date - anchor_date).days) <= 1
    if form in {"8-K", "8-K/A"} and "2.02" in items and same_or_near:
        return "high"
    if form in {"8-K", "8-K/A", "6-K", "6-K/A"} and same_or_near:
        return "medium"
    return "low"


def parse_acceptance_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(EASTERN)
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=EASTERN)
        return dt.astimezone(EASTERN)
    except ValueError:
        return None


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def filing_url(cik: str, accession: str, primary_doc: str) -> str:
    clean_cik = str(int(cik))
    clean_accession = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{clean_cik}/{clean_accession}/{primary_doc}"
