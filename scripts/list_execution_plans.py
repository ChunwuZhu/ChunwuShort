#!/usr/bin/env python3
"""List pre-trade execution plans."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.db import PaperOptionExecutionPlan, SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy-run-id", type=int)
    parser.add_argument("--ticker")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(PaperOptionExecutionPlan)
        if args.strategy_run_id:
            query = query.filter(PaperOptionExecutionPlan.strategy_run_id == args.strategy_run_id)
        if args.ticker:
            query = query.filter(PaperOptionExecutionPlan.ticker == args.ticker.upper())
        plans = query.order_by(
            PaperOptionExecutionPlan.strategy_run_id.desc(),
            PaperOptionExecutionPlan.strategy_index.asc(),
            PaperOptionExecutionPlan.id.desc(),
        ).all()
        payload = [_payload(plan) for plan in plans]
    finally:
        db.close()

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return
    if not payload:
        print("No execution plans found.")
        return
    for plan in payload:
        print(
            f"run={plan['strategy_run_id']} plan={plan['id']} s{plan['strategy_index']} "
            f"{plan['status']} conservative_debit={plan['conservative_net_debit']} "
            f"max_loss={plan['estimated_max_loss']} budget={plan['max_budget_to_use']} "
            f"max_spread={plan['max_spread_pct']}%"
        )
        messages = plan.get("messages") or []
        if messages:
            print("  " + "; ".join(messages))


def _payload(plan: PaperOptionExecutionPlan) -> dict:
    checks = plan.checks_json or {}
    return {
        "id": plan.id,
        "strategy_run_id": plan.strategy_run_id,
        "ticker": plan.ticker,
        "report_date": plan.report_date,
        "strategy_index": plan.strategy_index,
        "strategy_name": plan.strategy_name,
        "scenario": plan.scenario,
        "status": plan.status,
        "estimated_mid_debit": plan.estimated_mid_debit,
        "conservative_net_debit": plan.conservative_net_debit,
        "estimated_max_loss": plan.estimated_max_loss,
        "max_budget_to_use": plan.max_budget_to_use,
        "budget_ok": plan.budget_ok,
        "liquidity_ok": plan.liquidity_ok,
        "quote_fresh_ok": plan.quote_fresh_ok,
        "structure_ok": plan.structure_ok,
        "max_spread_pct": plan.max_spread_pct,
        "max_quote_age_minutes": plan.max_quote_age_minutes,
        "messages": checks.get("messages", []),
        "legs": plan.legs_json,
    }


if __name__ == "__main__":
    main()
