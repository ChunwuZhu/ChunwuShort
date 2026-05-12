#!/usr/bin/env python3
"""List adjusted-order suggestions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.db import PaperOptionAdjustmentSuggestion, SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy-run-id", type=int)
    parser.add_argument("--ticker")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(PaperOptionAdjustmentSuggestion)
        if args.strategy_run_id:
            query = query.filter(PaperOptionAdjustmentSuggestion.strategy_run_id == args.strategy_run_id)
        if args.ticker:
            query = query.filter(PaperOptionAdjustmentSuggestion.ticker == args.ticker.upper())
        rows = query.order_by(
            PaperOptionAdjustmentSuggestion.strategy_run_id.desc(),
            PaperOptionAdjustmentSuggestion.strategy_index.asc(),
            PaperOptionAdjustmentSuggestion.id.desc(),
        ).all()
        payload = [_payload(row) for row in rows]
    finally:
        db.close()

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return
    if not payload:
        print("No adjustment suggestions found.")
        return
    for row in payload:
        print(
            f"run={row['strategy_run_id']} suggestion={row['id']} s{row['strategy_index']} "
            f"{row['status']} recommendation={row['recommendation']} "
            f"qty={row['original_quantity']}->{row['suggested_quantity']} "
            f"debit={row['original_conservative_debit']}->{row['suggested_conservative_debit']} "
            f"budget={row['budget_limit']}"
        )
        if row["reasons"]:
            print("  " + "; ".join(row["reasons"]))


def _payload(row: PaperOptionAdjustmentSuggestion) -> dict:
    return {
        "id": row.id,
        "execution_plan_id": row.execution_plan_id,
        "strategy_run_id": row.strategy_run_id,
        "ticker": row.ticker,
        "report_date": row.report_date,
        "strategy_index": row.strategy_index,
        "strategy_name": row.strategy_name,
        "status": row.status,
        "recommendation": row.recommendation,
        "original_quantity": row.original_quantity,
        "suggested_quantity": row.suggested_quantity,
        "original_conservative_debit": row.original_conservative_debit,
        "suggested_conservative_debit": row.suggested_conservative_debit,
        "budget_limit": row.budget_limit,
        "max_spread_pct": row.max_spread_pct,
        "reasons": row.reason_json or [],
        "suggested_legs": row.suggested_legs_json or [],
    }


if __name__ == "__main__":
    main()
