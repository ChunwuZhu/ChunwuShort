#!/usr/bin/env python3
"""Refresh Moomoo paper status for an exit order batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.exit_batch_submission import refresh_exit_order_batch_status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exit-order-batch-id", type=int, required=True)
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = refresh_exit_order_batch_status(
        exit_order_batch_id=args.exit_order_batch_id,
        notify=args.notify,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"exit_order_batch_id={result['exit_order_batch_id']} status={result['status']}")
        for item in result["changed"]:
            print(
                f"  leg={item['leg_id']} order={item['broker_order_id']} "
                f"{item['old_status']}->{item['new_status']}"
            )


if __name__ == "__main__":
    main()
