#!/usr/bin/env python3
"""Build and optionally persist an earnings news summary from QC news CSVs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.news_summary import build_news_summary_from_csvs, upsert_news_summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--company-name")
    parser.add_argument("--provider")
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    summary = build_news_summary_from_csvs(
        ticker=args.ticker,
        report_date=_parse_date(args.report_date),
        paths=args.paths,
        company_name=args.company_name,
        provider=args.provider,
    )
    if args.persist:
        summary["news_summary_id"] = upsert_news_summary(summary)

    text = json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {path}")
    else:
        print(text)


def _parse_date(value):
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return datetime.strptime(text, "%Y-%m-%d").date()


if __name__ == "__main__":
    main()
