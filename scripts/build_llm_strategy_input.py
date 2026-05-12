#!/usr/bin/env python3
"""Build a JSON payload for earnings-options LLM strategy analysis."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.strategy_input_assembler import build_strategy_input


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True, help="Target ticker, e.g. ACM")
    parser.add_argument("--budget", required=True, type=float, help="Paper-trading budget for this analysis")
    parser.add_argument("--report-date", help="Optional report date, YYYY-MM-DD")
    parser.add_argument("--historical-earnings-limit", type=int, default=12)
    parser.add_argument("--include-full-fundamental-json", action="store_true")
    parser.add_argument("--output", help="Optional output JSON path")
    args = parser.parse_args()

    payload = build_strategy_input(
        ticker=args.ticker,
        budget=args.budget,
        report_date=args.report_date,
        historical_earnings_limit=args.historical_earnings_limit,
        include_full_fundamental_json=args.include_full_fundamental_json,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {path}")
    else:
        print(text)


if __name__ == "__main__":
    main()
