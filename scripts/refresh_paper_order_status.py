#!/usr/bin/env python3
"""Refresh Moomoo paper order status for submitted option batches."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.order_monitor import refresh_paper_order_batches
from utils.db import init_db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-batch-id", type=int)
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.init_db:
        init_db()
    result = refresh_paper_order_batches(order_batch_id=args.order_batch_id, notify=args.notify)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"batch_count={result['batch_count']} changed_count={result['changed_count']} "
            f"refreshed={result['refreshed']}"
        )
        for event in result["changed_events"]:
            print(
                f"  batch={event['order_batch_id']} leg={event['leg_index']} "
                f"{event['old_status']}->{event['new_status']} "
                f"filled={event['dealt_qty']} avg={event['dealt_avg_price']}"
            )


if __name__ == "__main__":
    main()
