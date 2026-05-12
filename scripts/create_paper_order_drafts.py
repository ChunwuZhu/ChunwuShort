#!/usr/bin/env python3
"""Persist LLM strategy JSON as paper option order drafts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.order_drafts import create_order_drafts_from_files
from utils.db import init_db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy-json", required=True)
    parser.add_argument("--input-json")
    parser.add_argument("--provider")
    parser.add_argument("--account")
    parser.add_argument("--model")
    parser.add_argument("--resolve-moomoo", action="store_true")
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.init_db:
        init_db()

    result = create_order_drafts_from_files(
        strategy_json_path=args.strategy_json,
        input_json_path=args.input_json,
        provider=args.provider,
        account=args.account,
        model=args.model,
        resolve_moomoo=args.resolve_moomoo,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"strategy_run_id={result['strategy_run_id']} "
            f"ticker={result['ticker']} report_date={result['report_date']} "
            f"draft_count={result['draft_count']} statuses={result['statuses']}"
        )


if __name__ == "__main__":
    main()
