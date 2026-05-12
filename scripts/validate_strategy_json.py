#!/usr/bin/env python3
"""Validate an earnings-options strategy JSON against local risk rules."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.strategy_quality import evaluate_strategy_quality


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Prepared LLM input JSON")
    parser.add_argument("--strategy", required=True, help="LLM strategy JSON")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    input_data = _read_json(args.input)
    strategy_json = _read_json(args.strategy)
    result = evaluate_strategy_quality(input_data=input_data, strategy_json=strategy_json)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return
    print(
        f"paper_trade_ready={result['paper_trade_ready']} "
        f"message_count={result['message_count']} "
        f"allowed_budget={result['allowed_budget']}"
    )
    for message in result["messages"]:
        print(f"  {message}")


def _read_json(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


if __name__ == "__main__":
    main()
