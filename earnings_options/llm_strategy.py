import json
import logging
import re
from copy import deepcopy
from typing import Any

from earnings_options.strategy_quality import evaluate_strategy_quality
from llm.tamu_client import TamuChatClient

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 120
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 8192
DEFAULT_MODEL = "protected.Claude Sonnet 4.6"

REQUIRED_INPUT_FIELDS = (
    "ticker",
    "budget",
    "earnings_date",
    "stock_data",
    "option_chain_data",
    "news",
    "historical_earnings",
)


class EarningsOptionsStrategyError(RuntimeError):
    pass


def analyze_earnings_options_strategy(
    input_data: dict[str, Any],
    *,
    client: TamuChatClient | None = None,
    model: str | None = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """Generate paper-trade-ready earnings option strategy ideas.

    The function only calls the LLM and returns structured analysis. It does not
    submit orders or call the Moomoo paper-trading module.
    """
    payload = _prepare_input(input_data)
    messages = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": _user_prompt(payload)},
    ]

    content = _chat_completion(messages, client=client, model=model, temperature=temperature, max_tokens=max_tokens)
    try:
        return _with_quality_metadata(payload, _parse_json_response(content))
    except EarningsOptionsStrategyError:
        logger.warning("LLM returned invalid JSON; retrying JSON repair")

    repair_messages = [
        {"role": "system", "content": _json_repair_prompt()},
        {"role": "user", "content": content},
    ]
    repaired = _chat_completion(
        repair_messages,
        client=client,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return _with_quality_metadata(payload, _parse_json_response(repaired))


def test_tamu_models() -> list[dict[str, Any]]:
    """Probe configured TAMU model names and return per-model results."""
    return [result.__dict__ for result in TamuChatClient().test_models()]


def _prepare_input(input_data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(input_data, dict):
        raise EarningsOptionsStrategyError("input_data must be a dict")

    payload = deepcopy(input_data)
    missing = [field for field in REQUIRED_INPUT_FIELDS if field not in payload]
    payload.setdefault("metadata", {})
    payload["metadata"]["missing_required_fields"] = missing
    payload["metadata"].setdefault("risk_profile", "aggressive")
    payload["metadata"].setdefault("strategy_count", 3)
    payload["metadata"].setdefault("execution_mode", "analysis_only")
    return payload


def _chat_completion(
    messages: list[dict[str, str]],
    *,
    client: TamuChatClient | None = None,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
) -> str:
    try:
        chat_client = client or TamuChatClient(timeout_sec=DEFAULT_TIMEOUT_SEC)
        return chat_client.complete(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as exc:
        raise EarningsOptionsStrategyError(str(exc)) from exc


def _parse_json_response(content: str) -> dict[str, Any]:
    cleaned = _strip_code_fence(content)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise EarningsOptionsStrategyError("LLM response did not contain a JSON object")
        data = json.loads(match.group(0))

    if not isinstance(data, dict):
        raise EarningsOptionsStrategyError("LLM JSON response must be an object")
    strategies = data.get("strategies")
    if not isinstance(strategies, list) or len(strategies) != 3:
        raise EarningsOptionsStrategyError("LLM response must include exactly 3 strategies")
    return data


def _with_quality_metadata(input_payload: dict[str, Any], strategy_json: dict[str, Any]) -> dict[str, Any]:
    quality = evaluate_strategy_quality(input_data=input_payload, strategy_json=strategy_json)
    strategy_json.setdefault("metadata", {})
    strategy_json["metadata"]["local_quality"] = quality
    warnings = list(strategy_json.get("data_quality_warnings") or [])
    warnings.extend(quality["messages"])
    strategy_json["data_quality_warnings"] = sorted(set(str(item) for item in warnings))
    for item, result in zip(strategy_json.get("strategies") or [], quality["strategy_results"]):
        item["local_quality"] = result
        if result["messages"]:
            item["paper_trade_ready"] = False
    return strategy_json


def _strip_code_fence(content: str) -> str:
    content = content.strip()
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE).strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content)
    return content.strip()


def _system_prompt() -> str:
    return """
You are an earnings-options strategy analyst for research and paper trading.
Your output will be used by a separate Moomoo paper-trading module, but you must
not place orders and must not claim certainty.

Return only valid JSON. Do not include Markdown, commentary, or code fences.

You must produce exactly 3 aggressive but defined-risk paper-trading strategies
for an earnings event. Undefined-risk naked short options are not allowed.
Strategies may include long calls/puts, debit spreads, calendars, diagonals,
straddles, strangles, or other defined-risk option combinations.

Use the provided option chain when choosing expiry, strike, quantity, and price
hints. Prefer exact contracts from option_chain_data.tradable_candidates when
available. If you choose a contract outside those candidates, explicitly explain
why in main_risks and set paper_trade_ready to false.

Budget and risk rules:
- Never use more than 95% of the stated budget.
- Use conservative entry pricing: BUY legs near ask, SELL legs near bid.
- Avoid contracts with wide spreads unless paper_trade_ready is false.
- Explain implied-volatility crush risk for every long-premium earnings trade.
- Any short option leg must be protected by a same-expiry long option leg.
- The max_loss value must be a dollar amount and must not exceed the strategy budget.

If the data is insufficient for a paper-trade-ready plan, set paper_trade_ready
to false and explain what is missing.

Required JSON shape:
{
  "ticker": "string",
  "summary": "string",
  "market_view": "string",
  "data_quality_warnings": ["string"],
  "strategies": [
    {
      "name": "string",
      "scenario": "bullish/base/bearish or similar",
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
        "Analyze the following earnings-trade input and return the required JSON. "
        "The user is aggressive and may use up to 95% of the stated budget, but "
        "all strategies must remain defined-risk and suitable for paper trading.\n\n"
        + json.dumps(payload, ensure_ascii=False, default=str)
    )


def _json_repair_prompt() -> str:
    return """
You repair invalid model output into valid JSON only.
Return one JSON object, no Markdown, no explanation.
The JSON must include exactly 3 strategies and follow the requested schema.
""".strip()
