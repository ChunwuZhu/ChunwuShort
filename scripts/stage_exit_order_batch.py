#!/usr/bin/env python3
"""Stage an approved exit confirmation as a paper exit order batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.exit_workflow import stage_exit_order_batch
from utils.db import init_db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exit-approval-id", type=int, required=True)
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.init_db:
        init_db()
    result = stage_exit_order_batch(exit_approval_id=args.exit_approval_id)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"exit_order_batch_id={result['exit_order_batch_id']} "
            f"status={result['status']} created={result['created']}"
        )


if __name__ == "__main__":
    main()
