#!/usr/bin/env python3
"""Download upcoming earnings events from QuantConnect EODHDUpcomingEarnings."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qc.earnings_calendar import (
    default_end,
    default_run_date,
    default_start,
    download_upcoming_earnings,
    normalize_date,
    write_outputs,
)


def print_summary(rows: list[dict]) -> None:
    if not rows:
        print("  No earnings events returned.")
        return
    by_date: dict[str, list[dict]] = {}
    for row in rows:
        by_date.setdefault(row.get("report_date", ""), []).append(row)
    print("\nUpcoming earnings returned by QuantConnect:")
    for report_date, items in sorted(by_date.items()):
        tickers = ", ".join(sorted(row["ticker"] for row in items if row.get("ticker")))
        print(f"  {report_date}: {len(items):3d}  {tickers}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download QC EODHD upcoming earnings calendar.")
    parser.add_argument("--run-date", default=None, help="QC data date, YYYY-MM-DD or YYYYMMDD. Default: latest weekday.")
    parser.add_argument("--start", "-s", default=None, help="Report start date. Default: day after --run-date.")
    parser.add_argument("--end", "-e", default=None, help="Report end date, YYYY-MM-DD or YYYYMMDD.")
    parser.add_argument("--days", type=int, default=14, help="End date offset if --end is omitted. Default: 14.")
    parser.add_argument("--max-events", default="10000", help="Maximum events to export from QC runtime stats.")
    args = parser.parse_args()

    run_date = normalize_date(args.run_date) if args.run_date else default_run_date()
    start = normalize_date(args.start) if args.start else default_start(run_date)
    end = normalize_date(args.end) if args.end else default_end(start, args.days)

    print("=" * 60)
    print(f"QC earnings calendar download as of {run_date}; reports {start} -> {end}")
    print("=" * 60)
    rows = download_upcoming_earnings(
        run_date=run_date,
        start=start,
        end=end,
        max_events=int(args.max_events),
        save_outputs=False,
    )
    csv_path, json_path = write_outputs(rows, start, end)
    print_summary(rows)
    print(f"\nSaved CSV:  {csv_path}")
    print(f"Saved JSON: {json_path}")
    print(
        "\nNote: QuantConnect EODHDUpcomingEarnings is documented as a daily universe "
        "for reports in the upcoming 7 days."
    )


if __name__ == "__main__":
    main()
