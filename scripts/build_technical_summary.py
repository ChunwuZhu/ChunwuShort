#!/usr/bin/env python3
"""Build a local technical summary from already-downloaded equity Parquet files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.data_job_worker import equity_price_windows
from earnings_options.technical_indicators import build_technical_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build local equity technical summary.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--report-date", required=True)
    args = parser.parse_args()

    report_date = _parse_date(args.report_date)
    windows = equity_price_windows(report_date)
    summary = build_technical_summary(ticker=args.ticker, report_date=report_date, windows=windows)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def _parse_date(value):
    from datetime import datetime

    text = value.strip()
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return datetime.strptime(text, "%Y-%m-%d").date()


if __name__ == "__main__":
    main()
