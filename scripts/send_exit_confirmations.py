#!/usr/bin/env python3
"""Send Telegram confirmations for actionable exit plans."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.exit_workflow import send_exit_confirmations
from utils.db import init_db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-batch-id", type=int)
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.init_db:
        init_db()
    result = send_exit_confirmations(order_batch_id=args.order_batch_id)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"sent_count={result['sent_count']} sent={result['sent']}")


if __name__ == "__main__":
    main()
