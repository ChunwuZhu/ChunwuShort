#!/usr/bin/env python3
"""Check data readiness before earnings-options LLM analysis."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.data_readiness import check_ticker_readiness, check_watchlist_readiness
from utils.db import init_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Check earnings-options data readiness.")
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.init_db:
        init_db()

    if args.ticker:
        results = [check_ticker_readiness(args.ticker)]
    else:
        results = check_watchlist_readiness(limit=args.limit)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return

    if not results:
        print("No watchlist events to check.")
        return
    for result in results:
        print(
            f"{result['ticker']:6s} {result['report_date']} {result['status']} "
            f"required_missing={len(result['required_missing'])} "
            f"optional_missing={len(result['optional_missing'])}"
        )
        if result["required_missing"]:
            print(f"  required: {', '.join(result['required_missing'])}")
        if result["optional_missing"]:
            print(f"  optional: {', '.join(result['optional_missing'])}")


if __name__ == "__main__":
    main()
