"""Gemini strategy generation for earnings option research."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from llm.gemini_client import GeminiClient

DEFAULT_MAX_OUTPUT_TOKENS = 8192
DEFAULT_TEMPERATURE = 0.2


class GeminiStrategyError(RuntimeError):
    pass


def analyze_strategy_input_with_gemini(
    input_payload: dict[str, Any],
    *,
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> dict[str, Any]:
    """Call Gemini and return a validated strategy JSON object."""
    payload = _prepare_payload(input_payload)
    response = GeminiClient().generate_json(
        system_instruction=_system_prompt(),
        user_content=_user_prompt(payload),
        model=model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    try:
        result = _parse_strategy_json(response.text)
    except GeminiStrategyError:
        repaired = GeminiClient().generate_json(
            system_instruction=_repair_prompt(),
            user_content=response.text,
            model=model,
            temperature=0,
            max_output_tokens=max_output_tokens,
        )
        result = _parse_strategy_json(repaired.text)

    result.setdefault("metadata", {})
    result["metadata"]["model"] = response.model
    result["metadata"]["source_input_schema"] = payload.get("metadata", {}).get("schema")
    result["metadata"]["execution_mode"] = "analysis_only"
    return result


def _prepare_payload(input_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(input_payload, dict):
        raise GeminiStrategyError("input_payload must be a JSON object")
    payload = deepcopy(input_payload)
    payload.setdefault("llm_instructions", {})
    payload["llm_instructions"].setdefault("strategy_requirement", "defined_risk_options_only")
    payload["llm_instructions"].setdefault("output_use", "moomoo_paper_trading_plan")
    return payload


def _parse_strategy_json(text: str) -> dict[str, Any]:
    cleaned = _strip_code_fence(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise GeminiStrategyError("Gemini response did not contain a JSON object")
        data = json.loads(match.group(0))

    if not isinstance(data, dict):
        raise GeminiStrategyError("Gemini response must be a JSON object")
    strategies = data.get("strategies")
    if not isinstance(strategies, list) or len(strategies) != 3:
        raise GeminiStrategyError("Gemini response must include exactly 3 strategies")
    for index, strategy in enumerate(strategies, start=1):
        if not isinstance(strategy, dict):
            raise GeminiStrategyError(f"strategy {index} must be an object")
        legs = strategy.get("legs")
        if not isinstance(legs, list) or not legs:
            raise GeminiStrategyError(f"strategy {index} must include non-empty legs")
    return data


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _system_prompt() -> str:
    return """
You are an earnings-options strategy analyst for research and paper trading.
Return only valid JSON. Do not include Markdown or code fences.

The user wants actionable but defined-risk option strategy plans that can later
be converted into Moomoo paper-trading orders by a separate module. You do not
place trades. You do not claim certainty.

Use the target stock data as the primary signal. SPY/QQQ benchmark data is only
context for market background. If option-chain data is thin, stale, or missing,
mark paper_trade_ready as false for affected strategies.

You must return exactly 3 strategies:
1. one bullish scenario
2. one bearish scenario
3. one base/volatility scenario

All strategies must be defined-risk. Naked short options are not allowed.
Prefer liquid contracts from the provided option summary. If exact contract
quotes are unavailable, use price hints and explain the uncertainty.

Required JSON shape:
{
  "ticker": "string",
  "summary": "string",
  "market_view": "string",
  "data_quality_warnings": ["string"],
  "strategies": [
    {
      "name": "string",
      "scenario": "bullish/base/bearish/volatility",
      "direction": "string",
      "entry_timing": "string",
      "exit_timing": "string",
      "max_budget_to_use": number,
      "estimated_entry_price": number,
      "legs": [
        {
          "action": "BUY or SELL",
          "option_type": "CALL or PUT",
          "expiry": "YYYY-MM-DD",
          "strike": number,
          "quantity": number,
          "limit_price_hint": number
        }
      ],
      "max_loss": number,
      "target_profit": "string or number",
      "break_even": "string",
      "main_risks": ["string"],
      "why_this_strategy": "string",
      "paper_trade_ready": true
    }
  ],
  "execution_notes": ["string"],
  "missing_data_that_would_improve_analysis": ["string"]
}
""".strip()


def _user_prompt(payload: dict[str, Any]) -> str:
    return (
        "Analyze this earnings-options input and produce the required strategy JSON. "
        "The user may allocate up to 95% of the stated budget, but every strategy "
        "must remain defined-risk and suitable for paper trading only.\n\n"
        + json.dumps(payload, ensure_ascii=False, default=str)
    )


def _repair_prompt() -> str:
    return """
Repair the following model output into one valid JSON object only.
Do not add Markdown or explanation.
The JSON must include exactly 3 strategies and follow the requested schema.
""".strip()
