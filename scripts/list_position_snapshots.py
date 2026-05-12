#!/usr/bin/env python3
"""List paper option position snapshots and exit plans."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.db import PaperOptionExitPlan, PaperOptionPositionSnapshot, SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-batch-id", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(PaperOptionPositionSnapshot)
        if args.order_batch_id:
            query = query.filter(PaperOptionPositionSnapshot.order_batch_id == args.order_batch_id)
        snapshots = query.order_by(PaperOptionPositionSnapshot.id.desc()).all()
        payload = [_payload(db, snapshot) for snapshot in snapshots]
    finally:
        db.close()

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return
    if not payload:
        print("No position snapshots found.")
        return
    for item in payload:
        exit_plan = item.get("exit_plan") or {}
        print(
            f"snapshot={item['id']} batch={item['order_batch_id']} "
            f"pl={item['unrealized_pl']} ({item['unrealized_pl_pct']}%) "
            f"exit={exit_plan.get('action')}/{exit_plan.get('status')}"
        )


def _payload(db, snapshot: PaperOptionPositionSnapshot) -> dict:
    exit_plan = (
        db.query(PaperOptionExitPlan)
        .filter(PaperOptionExitPlan.position_snapshot_id == snapshot.id)
        .order_by(PaperOptionExitPlan.id.desc())
        .first()
    )
    return {
        "id": snapshot.id,
        "order_batch_id": snapshot.order_batch_id,
        "strategy_run_id": snapshot.strategy_run_id,
        "ticker": snapshot.ticker,
        "status": snapshot.status,
        "entry_net_debit": snapshot.entry_net_debit,
        "current_exit_value": snapshot.current_exit_value,
        "unrealized_pl": snapshot.unrealized_pl,
        "unrealized_pl_pct": snapshot.unrealized_pl_pct,
        "max_profit": snapshot.max_profit,
        "max_loss": snapshot.max_loss,
        "created_at": snapshot.created_at,
        "exit_plan": _exit_payload(exit_plan),
    }


def _exit_payload(exit_plan: PaperOptionExitPlan | None) -> dict | None:
    if exit_plan is None:
        return None
    return {
        "id": exit_plan.id,
        "action": exit_plan.action,
        "status": exit_plan.status,
        "reasons": exit_plan.reason_json or [],
        "exit_legs": exit_plan.exit_legs_json or [],
        "created_at": exit_plan.created_at,
    }


if __name__ == "__main__":
    main()
