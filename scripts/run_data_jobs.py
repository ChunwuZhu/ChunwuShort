#!/usr/bin/env python3
"""Run pending earnings-options enrichment jobs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.data_job_worker import run_pending_jobs
from earnings_options.db_migrations import run_migrations


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pending earnings-options data jobs.")
    parser.add_argument("--job-type", default="historical_equity_prices")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--init-db", action="store_true")
    args = parser.parse_args()

    if args.init_db:
        run_migrations()
    results = run_pending_jobs(job_type=args.job_type, limit=args.limit)
    if not results:
        print("No pending jobs.")
        return
    print("Data jobs complete:")
    for result in results:
        print(f"  {result}")


if __name__ == "__main__":
    main()
