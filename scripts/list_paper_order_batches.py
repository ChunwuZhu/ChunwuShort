#!/usr/bin/env python3
"""List staged paper option order batches."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.db import PaperOptionOrderBatch, PaperOptionOrderBatchLeg, SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-batch-id", type=int)
    parser.add_argument("--approval-id", type=int)
    parser.add_argument("--strategy-run-id", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(PaperOptionOrderBatch)
        if args.order_batch_id:
            query = query.filter(PaperOptionOrderBatch.id == args.order_batch_id)
        if args.approval_id:
            query = query.filter(PaperOptionOrderBatch.manual_approval_id == args.approval_id)
        if args.strategy_run_id:
            query = query.filter(PaperOptionOrderBatch.strategy_run_id == args.strategy_run_id)
        batches = query.order_by(PaperOptionOrderBatch.id.desc()).all()
        payload = [_payload(db, batch) for batch in batches]
    finally:
        db.close()

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return
    if not payload:
        print("No paper order batches found.")
        return
    for batch in payload:
        print(
            f"batch={batch['id']} approval={batch['manual_approval_id']} "
            f"run={batch['strategy_run_id']} status={batch['status']} "
            f"estimated_cost={batch['estimated_cost']}"
        )
        for leg in batch["legs"]:
            print(
                f"  l{leg['leg_index']} {leg['action']} {leg['quantity']} "
                f"{leg['broker_code']} limit={leg['suggested_limit_price']} status={leg['status']}"
            )


def _payload(db, batch: PaperOptionOrderBatch) -> dict:
    legs = (
        db.query(PaperOptionOrderBatchLeg)
        .filter(PaperOptionOrderBatchLeg.order_batch_id == batch.id)
        .order_by(PaperOptionOrderBatchLeg.leg_index.asc())
        .all()
    )
    return {
        "id": batch.id,
        "manual_approval_id": batch.manual_approval_id,
        "adjustment_suggestion_id": batch.adjustment_suggestion_id,
        "strategy_run_id": batch.strategy_run_id,
        "ticker": batch.ticker,
        "report_date": batch.report_date,
        "strategy_index": batch.strategy_index,
        "strategy_name": batch.strategy_name,
        "status": batch.status,
        "estimated_cost": batch.estimated_cost,
        "created_at": batch.created_at,
        "legs": [_leg_payload(leg) for leg in legs],
    }


def _leg_payload(leg: PaperOptionOrderBatchLeg) -> dict:
    return {
        "id": leg.id,
        "leg_index": leg.leg_index,
        "action": leg.action,
        "option_type": leg.option_type,
        "expiry": leg.expiry,
        "strike": leg.strike,
        "quantity": leg.quantity,
        "broker_code": leg.broker_code,
        "occ_symbol": leg.occ_symbol,
        "suggested_limit_price": leg.suggested_limit_price,
        "order_type": leg.order_type,
        "status": leg.status,
        "broker_order_id": leg.broker_order_id,
    }


if __name__ == "__main__":
    main()
