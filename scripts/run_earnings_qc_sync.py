#!/usr/bin/env python3
"""Run the QuantConnect earnings/fundamental sync."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.qc_data_sync import sync_from_files, sync_from_quantconnect
from utils.db import init_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync QC earnings and fundamentals into PostgreSQL.")
    parser.add_argument("--run-date", default=None, help="YYYY-MM-DD or YYYYMMDD. Default: latest weekday.")
    parser.add_argument("--start", default=None, help="Report start date. Default: run date.")
    parser.add_argument("--end", default=None, help="Report end date. Default: start + --days.")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--earnings-json", type=Path, default=None, help="Use existing earnings JSON instead of QC API.")
    parser.add_argument("--fundamentals-json", type=Path, default=None, help="Use existing fundamentals JSON instead of QC API.")
    parser.add_argument("--init-db", action="store_true", help="Create missing DB tables before syncing.")
    args = parser.parse_args()

    if args.init_db:
        init_db()

    if args.earnings_json or args.fundamentals_json:
        if not (args.earnings_json and args.fundamentals_json and args.run_date and args.start and args.end):
            raise SystemExit(
                "--earnings-json and --fundamentals-json require --run-date, --start, and --end"
            )
        result = sync_from_files(
            earnings_json=args.earnings_json,
            fundamentals_json=args.fundamentals_json,
            run_date=args.run_date,
            requested_start=args.start,
            requested_end=args.end,
        )
    else:
        result = sync_from_quantconnect(
            run_date=args.run_date,
            start=args.start,
            end=args.end,
            days=args.days,
        )

    print("Earnings QC sync complete:")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
