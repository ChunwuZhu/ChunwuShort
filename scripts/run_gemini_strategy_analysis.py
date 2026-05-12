#!/usr/bin/env python3
"""Run Gemini earnings-options strategy analysis from a prepared JSON input."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.gemini_strategy import analyze_strategy_input_with_gemini
from earnings_options.strategy_input_assembler import build_strategy_input
from llm.gemini_client import GeminiClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", help="Prepared strategy input JSON path")
    source.add_argument("--ticker", help="Build input from local DB for this ticker")
    parser.add_argument("--budget", type=float, help="Required with --ticker")
    parser.add_argument("--report-date", help="Optional report date, YYYY-MM-DD")
    parser.add_argument("--model", help="Gemini model override")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--output", help="Optional output JSON path")
    parser.add_argument("--smoke-test", action="store_true", help="Only test Gemini connectivity")
    args = parser.parse_args()

    try:
        if args.smoke_test:
            response = GeminiClient(model=args.model).smoke_test(model=args.model)
            print(response.text)
            return

        if args.input:
            payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        elif args.ticker:
            if args.budget is None:
                parser.error("--budget is required with --ticker")
            payload = build_strategy_input(
                ticker=args.ticker,
                budget=args.budget,
                report_date=args.report_date,
            )
        else:
            parser.error("Use --input, --ticker, or --smoke-test")

        result = analyze_strategy_input_with_gemini(
            payload,
            model=args.model,
            temperature=args.temperature,
            max_output_tokens=args.max_output_tokens,
        )
        text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
            print(f"wrote {path}")
        else:
            print(text)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
