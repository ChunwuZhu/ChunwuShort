#!/usr/bin/env python3
"""Refresh position valuation and exit-plan suggestion for a filled batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.position_monitor import refresh_position_snapshot
from utils.db import init_db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-batch-id", type=int, required=True)
    parser.add_argument("--take-profit-pct", type=float, default=50)
    parser.add_argument("--stop-loss-pct", type=float, default=-50)
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.init_db:
        init_db()
    result = refresh_position_snapshot(
        order_batch_id=args.order_batch_id,
        take_profit_pct=args.take_profit_pct,
        stop_loss_pct=args.stop_loss_pct,
        notify=args.notify,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"batch={result['order_batch_id']} snapshot={result['position_snapshot_id']} "
            f"pl={result['unrealized_pl']} ({result['unrealized_pl_pct']}%) "
            f"exit={result['exit_action']}/{result['exit_status']}"
        )


if __name__ == "__main__":
    main()
