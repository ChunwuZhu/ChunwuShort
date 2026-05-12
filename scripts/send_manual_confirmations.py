#!/usr/bin/env python3
"""Send Telegram manual confirmation requests for adjusted option plans."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.manual_confirmation import send_manual_confirmations
from utils.db import init_db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy-run-id", type=int, required=True)
    parser.add_argument("--include-not-recommended", action="store_true")
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.init_db:
        init_db()
    result = send_manual_confirmations(
        strategy_run_id=args.strategy_run_id,
        only_ready=not args.include_not_recommended,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"strategy_run_id={result['strategy_run_id']} sent_count={result['sent_count']}")


if __name__ == "__main__":
    main()
