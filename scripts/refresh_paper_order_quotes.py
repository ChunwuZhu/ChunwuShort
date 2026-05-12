#!/usr/bin/env python3
"""Resolve Moomoo option contracts and refresh quotes for order drafts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.broker_mapping import refresh_order_draft_quotes
from utils.db import init_db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy-run-id", type=int)
    parser.add_argument("--ticker")
    parser.add_argument("--draft-id", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.init_db:
        init_db()
    result = refresh_order_draft_quotes(
        strategy_run_id=args.strategy_run_id,
        ticker=args.ticker,
        draft_id=args.draft_id,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"draft_count={result['draft_count']} resolved={result['resolved']} "
            f"quoted={result['quoted']} needs_review={result['needs_review']}"
        )
        for error in result["errors"]:
            print(f"draft={error['draft_id']} error={error['error']}")


if __name__ == "__main__":
    main()
