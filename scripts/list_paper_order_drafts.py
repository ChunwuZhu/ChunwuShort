#!/usr/bin/env python3
"""List persisted paper option order drafts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.db import PaperOptionOrderDraft, PaperOptionQuoteSnapshot, SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy-run-id", type=int)
    parser.add_argument("--ticker")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(PaperOptionOrderDraft)
        if args.strategy_run_id:
            query = query.filter(PaperOptionOrderDraft.strategy_run_id == args.strategy_run_id)
        if args.ticker:
            query = query.filter(PaperOptionOrderDraft.ticker == args.ticker.upper())
        rows = query.order_by(
            PaperOptionOrderDraft.strategy_run_id.desc(),
            PaperOptionOrderDraft.strategy_index.asc(),
            PaperOptionOrderDraft.leg_index.asc(),
        ).all()
        payload = [_row_payload(db, row) for row in rows]
    finally:
        db.close()

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return
    if not payload:
        print("No paper option order drafts found.")
        return
    for row in payload:
        print(
            f"run={row['strategy_run_id']} draft={row['id']} "
            f"s{row['strategy_index']}l{row['leg_index']} {row['action']} "
            f"{row['quantity']} {row['occ_symbol']} limit={row['limit_price_hint']} "
            f"broker={row['broker_code']} mid={row['latest_quote'].get('mid_price')} "
            f"status={row['validation_status']}"
        )


def _row_payload(db, row: PaperOptionOrderDraft) -> dict:
    quote = (
        db.query(PaperOptionQuoteSnapshot)
        .filter(PaperOptionQuoteSnapshot.order_draft_id == row.id)
        .order_by(PaperOptionQuoteSnapshot.id.desc())
        .first()
    )
    return {
        "id": row.id,
        "strategy_run_id": row.strategy_run_id,
        "ticker": row.ticker,
        "report_date": row.report_date,
        "strategy_index": row.strategy_index,
        "strategy_name": row.strategy_name,
        "scenario": row.scenario,
        "leg_index": row.leg_index,
        "action": row.action,
        "option_type": row.option_type,
        "expiry": row.expiry,
        "strike": row.strike,
        "quantity": row.quantity,
        "limit_price_hint": row.limit_price_hint,
        "occ_symbol": row.occ_symbol,
        "moomoo_code_candidate": row.moomoo_code_candidate,
        "broker_code": row.broker_code,
        "validation_status": row.validation_status,
        "validation_messages": row.validation_messages,
        "latest_quote": _quote_payload(quote),
    }


def _quote_payload(quote: PaperOptionQuoteSnapshot | None) -> dict:
    if quote is None:
        return {}
    return {
        "quote_snapshot_id": quote.id,
        "quote_time": quote.quote_time,
        "last_price": quote.last_price,
        "bid_price": quote.bid_price,
        "ask_price": quote.ask_price,
        "mid_price": quote.mid_price,
        "volume": quote.volume,
        "open_interest": quote.open_interest,
        "implied_volatility": quote.implied_volatility,
        "delta": quote.delta,
    }


if __name__ == "__main__":
    main()
