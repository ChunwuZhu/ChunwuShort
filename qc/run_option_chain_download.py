#!/usr/bin/env python3
"""Download wide option-chain minute data from QuantConnect into local Parquet."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qc.option_chain_downloader import download_option_chain


def main() -> None:
    parser = argparse.ArgumentParser(description="Download QC wide option-chain minute data.")
    parser.add_argument("--ticker", "-t", required=True)
    parser.add_argument("--start", "-s", required=True)
    parser.add_argument("--end", "-e", required=True)
    parser.add_argument("--min-strike-rank", type=int, default=-250)
    parser.add_argument("--max-strike-rank", type=int, default=250)
    parser.add_argument("--min-dte", type=int, default=0)
    parser.add_argument("--max-dte", type=int, default=180)
    parser.add_argument("--create-project", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print(
        f"QC wide option-chain download {args.ticker.upper()} {args.start} -> {args.end}; "
        f"strikes {args.min_strike_rank}:{args.max_strike_rank}, dte {args.min_dte}:{args.max_dte}"
    )
    print("=" * 60)
    paths = download_option_chain(
        ticker=args.ticker,
        start=args.start,
        end=args.end,
        min_strike_rank=args.min_strike_rank,
        max_strike_rank=args.max_strike_rank,
        min_dte=args.min_dte,
        max_dte=args.max_dte,
        create_project=args.create_project,
    )
    print(f"\nDone. Saved {len(paths)} parquet file(s).")
    for path in paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()
