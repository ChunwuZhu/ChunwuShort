#!/usr/bin/env python3
"""Build adjusted-order suggestions from execution plans."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.adjustment_suggestions import build_adjustment_suggestions
from utils.db import init_db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy-run-id", type=int, required=True)
    parser.add_argument("--max-spread-pct", type=float, default=35)
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.init_db:
        init_db()
    result = build_adjustment_suggestions(
        strategy_run_id=args.strategy_run_id,
        max_spread_pct=args.max_spread_pct,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"strategy_run_id={result['strategy_run_id']} "
            f"suggestion_count={result['suggestion_count']} "
            f"statuses={result['statuses']} recommendations={result['recommendations']}"
        )


if __name__ == "__main__":
    main()
