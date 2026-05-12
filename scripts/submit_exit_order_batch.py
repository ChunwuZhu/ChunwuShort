#!/usr/bin/env python3
"""Dry-run or submit a staged paper option exit order batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.exit_batch_submission import submit_exit_order_batch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exit-order-batch-id", type=int, required=True)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--wait", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = submit_exit_order_batch(
        exit_order_batch_id=args.exit_order_batch_id,
        submit=args.submit,
        wait_seconds=args.wait,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"exit_order_batch_id={result['exit_order_batch_id']} "
            f"mode={result['mode']} status={result['status']}"
        )
        for order in result.get("orders", []):
            print(
                f"  {order['action']} {order['quantity']} {order['broker_code']} "
                f"limit={order['limit_price']} status={order['status']}"
            )
        for order in result.get("submitted", []):
            print(f"  submitted leg={order['leg_id']} order_id={order['broker_order_id']}")
        for item in result.get("failed", []):
            print(f"  failed leg={item['leg_id']} {item['broker_code']} {item['message']}")


if __name__ == "__main__":
    main()
