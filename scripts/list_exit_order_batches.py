#!/usr/bin/env python3
"""List staged/submitted paper exit order batches."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.db import PaperOptionExitOrderBatch, PaperOptionExitOrderBatchLeg, SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exit-order-batch-id", type=int)
    parser.add_argument("--source-order-batch-id", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(PaperOptionExitOrderBatch)
        if args.exit_order_batch_id:
            query = query.filter(PaperOptionExitOrderBatch.id == args.exit_order_batch_id)
        if args.source_order_batch_id:
            query = query.filter(PaperOptionExitOrderBatch.source_order_batch_id == args.source_order_batch_id)
        batches = query.order_by(PaperOptionExitOrderBatch.id.desc()).all()
        payload = [_payload(db, batch) for batch in batches]
    finally:
        db.close()

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return
    if not payload:
        print("No exit order batches found.")
        return
    for batch in payload:
        print(
            f"exit_batch={batch['id']} source={batch['source_order_batch_id']} "
            f"status={batch['status']}"
        )
        for leg in batch["legs"]:
            print(
                f"  l{leg['leg_index']} {leg['action']} {leg['quantity']} "
                f"{leg['broker_code']} limit={leg['suggested_limit_price']} "
                f"status={leg['status']} order={leg['broker_order_id']}"
            )


def _payload(db, batch: PaperOptionExitOrderBatch) -> dict:
    legs = (
        db.query(PaperOptionExitOrderBatchLeg)
        .filter(PaperOptionExitOrderBatchLeg.exit_order_batch_id == batch.id)
        .order_by(PaperOptionExitOrderBatchLeg.leg_index.asc())
        .all()
    )
    return {
        "id": batch.id,
        "exit_approval_id": batch.exit_approval_id,
        "exit_plan_id": batch.exit_plan_id,
        "source_order_batch_id": batch.source_order_batch_id,
        "strategy_run_id": batch.strategy_run_id,
        "ticker": batch.ticker,
        "status": batch.status,
        "created_at": batch.created_at,
        "submitted_at": batch.submitted_at,
        "legs": [_leg_payload(leg) for leg in legs],
    }


def _leg_payload(leg: PaperOptionExitOrderBatchLeg) -> dict:
    return {
        "id": leg.id,
        "source_batch_leg_id": leg.source_batch_leg_id,
        "leg_index": leg.leg_index,
        "action": leg.action,
        "quantity": leg.quantity,
        "broker_code": leg.broker_code,
        "suggested_limit_price": leg.suggested_limit_price,
        "order_type": leg.order_type,
        "status": leg.status,
        "broker_order_id": leg.broker_order_id,
        "dealt_qty": leg.dealt_qty,
        "dealt_avg_price": leg.dealt_avg_price,
        "last_err_msg": leg.last_err_msg,
    }


if __name__ == "__main__":
    main()
