#!/usr/bin/env python3
"""Dry-run or submit a staged paper option order batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.batch_submission import submit_paper_order_batch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-batch-id", type=int, required=True)
    parser.add_argument("--submit", action="store_true", help="Actually call Moomoo paper place_order")
    parser.add_argument("--wait", type=int, default=0, help="Wait seconds per order after submission")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = submit_paper_order_batch(
        order_batch_id=args.order_batch_id,
        submit=args.submit,
        wait_seconds=args.wait,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"order_batch_id={result['order_batch_id']} mode={result['mode']} "
            f"status={result['status']}"
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
