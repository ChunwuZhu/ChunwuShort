#!/usr/bin/env python3
"""Refresh all open paper option positions and exit suggestions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.position_monitor import refresh_open_positions
from utils.db import init_db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--take-profit-pct", type=float, default=50)
    parser.add_argument("--stop-loss-pct", type=float, default=-50)
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.init_db:
        init_db()
    result = refresh_open_positions(
        take_profit_pct=args.take_profit_pct,
        stop_loss_pct=args.stop_loss_pct,
        notify=args.notify,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return
    print(
        f"batch_count={result['batch_count']} refreshed={result['refreshed_count']} "
        f"errors={result['error_count']}"
    )
    for item in result["results"]:
        print(
            f"  batch={item['order_batch_id']} pl={item['unrealized_pl']} "
            f"({item['unrealized_pl_pct']}%) exit={item['exit_action']}/{item['exit_status']}"
        )
    for error in result["errors"]:
        print(f"  error batch={error['order_batch_id']}: {error['error']}")


if __name__ == "__main__":
    main()
