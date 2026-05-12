#!/usr/bin/env python3
"""Run the morning earnings-options data pipeline before LLM analysis."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.data_job_worker import run_pending_jobs
from earnings_options.data_readiness import check_watchlist_readiness
from earnings_options.qc_data_sync import sync_from_quantconnect
from utils.db import init_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Run earnings sync and data enrichment in one morning batch.")
    parser.add_argument("--run-date", default=None, help="YYYY-MM-DD or YYYYMMDD. Default: latest weekday.")
    parser.add_argument("--start", default=None, help="Report start date. Default: run date.")
    parser.add_argument("--end", default=None, help="Report end date. Default: start + --days.")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--equity-job-limit", type=int, default=20)
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--skip-equity-jobs", action="store_true")
    parser.add_argument("--skip-readiness", action="store_true")
    parser.add_argument("--init-db", action="store_true")
    args = parser.parse_args()

    if args.init_db:
        init_db()

    if not args.skip_sync:
        sync_result = sync_from_quantconnect(
            run_date=args.run_date,
            start=args.start,
            end=args.end,
            days=args.days,
        )
        print("Earnings QC sync complete:")
        for key, value in sync_result.items():
            print(f"  {key}: {value}")

    if not args.skip_equity_jobs:
        job_results = run_pending_jobs(
            job_type="historical_equity_prices",
            limit=args.equity_job_limit,
        )
        if not job_results:
            print("No pending historical_equity_prices jobs.")
        else:
            print("Historical equity price jobs complete:")
            for result in job_results:
                print(f"  {result}")

    if not args.skip_readiness:
        readiness_results = check_watchlist_readiness(limit=args.equity_job_limit)
        if not readiness_results:
            print("No watchlist readiness checks.")
        else:
            print("Data readiness checks complete:")
            for result in readiness_results:
                print(
                    f"  {result['ticker']} {result['report_date']} {result['status']} "
                    f"required_missing={len(result['required_missing'])}"
                )


if __name__ == "__main__":
    main()
