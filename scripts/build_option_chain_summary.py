#!/usr/bin/env python3
"""Build option-chain summary from local option Parquet files."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.option_chain_summary import build_option_chain_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build option-chain summary from local parquet files.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--spot-price", type=float, required=True)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    report_date = _parse_date(args.report_date)
    summary = build_option_chain_summary(
        ticker=args.ticker,
        report_date=report_date,
        spot_price=args.spot_price,
        option_paths=args.paths,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def _parse_date(value):
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return datetime.strptime(text, "%Y-%m-%d").date()


if __name__ == "__main__":
    main()
