#!/usr/bin/env python3
"""Run TAMU Claude earnings-options strategy analysis."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_options.llm_strategy import analyze_earnings_options_strategy
from earnings_options.strategy_input_assembler import build_strategy_input
from llm.tamu_client import TamuChatClient
from utils.config import config

DEFAULT_MODEL = "protected.Claude Sonnet 4.6"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", help="Prepared strategy input JSON path")
    source.add_argument("--ticker", help="Build input from local DB for this ticker")
    parser.add_argument("--budget", type=float, help="Required with --ticker")
    parser.add_argument("--report-date", help="Optional report date, YYYY-MM-DD")
    parser.add_argument("--account", choices=("primary", "alt"), default="primary")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--output", help="Optional output JSON path")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()

    try:
        client = _client(args.account, args.model)
        if args.smoke_test:
            text = client.complete(
                [
                    {"role": "system", "content": "Return JSON only."},
                    {"role": "user", "content": 'Return exactly {"ok": true}'},
                ],
                model=args.model,
                max_tokens=2048,
                temperature=args.temperature,
            )
            print(text)
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

        result = analyze_earnings_options_strategy(
            payload,
            client=client,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        result.setdefault("metadata", {})
        result["metadata"]["provider"] = "tamu"
        result["metadata"]["account"] = args.account
        result["metadata"]["model"] = args.model
        result["metadata"]["execution_mode"] = "analysis_only"
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


def _client(account: str, model: str) -> TamuChatClient:
    if account == "alt":
        endpoint = config.TAMU_ALT_BASE_URL.rstrip("/") + "/openai/chat/completions"
        return TamuChatClient(
            api_key=config.TAMU_ALT_API_KEY,
            endpoint=endpoint,
            model=model,
            fallbacks=[],
            timeout_sec=120,
        )
    return TamuChatClient(
        api_key=config.TAMU_API_KEY,
        endpoint=config.TAMU_API_ENDPOINT,
        model=model,
        fallbacks=[],
        timeout_sec=120,
    )


if __name__ == "__main__":
    main()
