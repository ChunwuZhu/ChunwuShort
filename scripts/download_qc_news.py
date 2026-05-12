#!/usr/bin/env python3
"""Download QuantConnect news rows to local CSV."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qc.news_downloader import download_news


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--provider", choices=("tiingo", "benzinga", "both"), default="tiingo")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = download_news(
        ticker=args.ticker,
        start=_parse_date(args.start),
        end=_parse_date(args.end),
        provider=args.provider,
        save_outputs=not args.no_save,
    )
    payload = {key: value for key, value in result.items() if key != "rows"}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"ticker={payload['ticker']} provider={payload['provider']} "
            f"rows={payload['row_count']} path={payload['path']}"
        )


def _parse_date(value):
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return datetime.strptime(text, "%Y-%m-%d").date()


if __name__ == "__main__":
    main()
