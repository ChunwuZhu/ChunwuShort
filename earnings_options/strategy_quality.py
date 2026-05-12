"""Local validation for LLM-generated earnings option strategies."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

CONTRACT_MULTIPLIER = Decimal("100")
MAX_BUDGET_FRACTION = Decimal("0.95")
VALID_ACTIONS = {"BUY", "SELL"}
VALID_OPTION_TYPES = {"CALL", "PUT"}


def evaluate_strategy_quality(
    *,
    input_data: dict[str, Any],
    strategy_json: dict[str, Any],
) -> dict[str, Any]:
    """Return local warnings and readiness flags for a strategy JSON object."""
    budget = _decimal(input_data.get("budget"))
    option_summary = input_data.get("option_chain_data") or {}
    earnings_date = _parse_day(input_data.get("earnings_date"))
    allowed_budget = budget * MAX_BUDGET_FRACTION if budget is not None else None
    listed_contracts = _listed_contract_index(option_summary)

    strategy_results = []
    all_messages = []
    for index, strategy in enumerate(strategy_json.get("strategies") or [], start=1):
        result = _evaluate_one_strategy(
            strategy=strategy,
            index=index,
            allowed_budget=allowed_budget,
            earnings_date=earnings_date,
            listed_contracts=listed_contracts,
            option_summary=option_summary,
        )
        strategy_results.append(result)
        all_messages.extend(f"strategy_{index}:{message}" for message in result["messages"])

    return {
        "version": "strategy_quality_v1",
        "paper_trade_ready": not all_messages,
        "message_count": len(all_messages),
        "messages": all_messages,
        "budget": _float(budget),
        "allowed_budget": _float(allowed_budget),
        "strategy_results": strategy_results,
    }


def _evaluate_one_strategy(
    *,
    strategy: dict[str, Any],
    index: int,
    allowed_budget: Decimal | None,
    earnings_date: date | None,
    listed_contracts: set[tuple[str, date, Decimal]],
    option_summary: dict[str, Any],
) -> dict[str, Any]:
    messages = []
    legs = strategy.get("legs") or []
    if not legs:
        messages.append("missing_legs")
    if len(legs) > 4:
        messages.append("too_many_legs_for_first_execution_version")

    strategy_budget = _decimal(strategy.get("max_budget_to_use"))
    estimated_entry = _decimal(strategy.get("estimated_entry_price"))
    max_loss = _decimal(strategy.get("max_loss"))
    if strategy_budget is None or strategy_budget <= 0:
        messages.append("invalid_max_budget_to_use")
    elif allowed_budget is not None and strategy_budget > allowed_budget:
        messages.append(f"strategy_budget_exceeds_95pct_budget:{strategy_budget}>{allowed_budget}")
    if estimated_entry is None or estimated_entry <= 0:
        messages.append("invalid_estimated_entry_price")
    if max_loss is None or max_loss < 0:
        messages.append("invalid_max_loss")
    elif allowed_budget is not None and max_loss > allowed_budget:
        messages.append(f"max_loss_exceeds_95pct_budget:{max_loss}>{allowed_budget}")

    parsed_legs = []
    estimated_net_debit = Decimal("0")
    for leg_index, leg in enumerate(legs, start=1):
        parsed, leg_messages = _parse_leg(leg, leg_index, earnings_date, listed_contracts)
        parsed_legs.append(parsed)
        messages.extend(leg_messages)
        if parsed["price"] is not None and parsed["quantity"] is not None:
            sign = Decimal("1") if parsed["action"] == "BUY" else Decimal("-1")
            estimated_net_debit += sign * parsed["price"] * Decimal(parsed["quantity"]) * CONTRACT_MULTIPLIER

    messages.extend(_defined_risk_messages(parsed_legs))
    messages.extend(_liquidity_messages(option_summary))
    if allowed_budget is not None and max(estimated_net_debit, Decimal("0")) > allowed_budget:
        messages.append(f"estimated_net_debit_exceeds_95pct_budget:{estimated_net_debit}>{allowed_budget}")

    return {
        "strategy_index": index,
        "name": strategy.get("name"),
        "paper_trade_ready": not messages,
        "messages": messages,
        "estimated_net_debit_from_legs": _float(estimated_net_debit),
        "leg_count": len(legs),
    }


def _parse_leg(
    leg: dict[str, Any],
    leg_index: int,
    earnings_date: date | None,
    listed_contracts: set[tuple[str, date, Decimal]],
) -> tuple[dict[str, Any], list[str]]:
    messages = []
    action = str(leg.get("action") or "").upper()
    option_type = str(leg.get("option_type") or "").upper()
    expiry = _parse_day(leg.get("expiry"))
    strike = _decimal(leg.get("strike"))
    quantity = _int(leg.get("quantity"))
    price = _decimal(leg.get("limit_price_hint"))

    if action not in VALID_ACTIONS:
        messages.append(f"leg_{leg_index}:invalid_action")
    if option_type not in VALID_OPTION_TYPES:
        messages.append(f"leg_{leg_index}:invalid_option_type")
    if expiry is None:
        messages.append(f"leg_{leg_index}:invalid_expiry")
    elif earnings_date is not None and expiry < earnings_date:
        messages.append(f"leg_{leg_index}:expiry_before_earnings")
    if strike is None or strike <= 0:
        messages.append(f"leg_{leg_index}:invalid_strike")
    if quantity is None or quantity <= 0:
        messages.append(f"leg_{leg_index}:invalid_quantity")
    if price is None or price <= 0:
        messages.append(f"leg_{leg_index}:invalid_limit_price_hint")
    if listed_contracts and option_type in VALID_OPTION_TYPES and expiry and strike:
        if (option_type, expiry, strike) not in listed_contracts:
            messages.append(f"leg_{leg_index}:contract_not_in_compact_option_candidates")

    return {
        "action": action,
        "option_type": option_type,
        "expiry": expiry,
        "strike": strike,
        "quantity": quantity,
        "price": price,
    }, messages


def _defined_risk_messages(legs: list[dict[str, Any]]) -> list[str]:
    messages = []
    shorts = [leg for leg in legs if leg["action"] == "SELL"]
    if not shorts:
        return messages

    long_qty_by_type_expiry = defaultdict(int)
    short_qty_by_type_expiry = defaultdict(int)
    for leg in legs:
        if leg["option_type"] not in VALID_OPTION_TYPES or leg["expiry"] is None:
            continue
        quantity = leg["quantity"] or 0
        key = (leg["option_type"], leg["expiry"])
        if leg["action"] == "BUY":
            long_qty_by_type_expiry[key] += quantity
        elif leg["action"] == "SELL":
            short_qty_by_type_expiry[key] += quantity

    for short in shorts:
        if short["option_type"] not in VALID_OPTION_TYPES or short["expiry"] is None or short["strike"] is None:
            messages.append("short_leg_cannot_be_verified_defined_risk")
            continue
        key = (short["option_type"], short["expiry"])
        if long_qty_by_type_expiry[key] < short_qty_by_type_expiry[key]:
            messages.append("short_leg_without_same_expiry_protective_long")
    return messages


def _liquidity_messages(option_summary: dict[str, Any]) -> list[str]:
    messages = []
    liquidity_score = _decimal(option_summary.get("columns", {}).get("liquidity_score") or option_summary.get("liquidity_score"))
    median_spread = _decimal(option_summary.get("columns", {}).get("median_spread_pct") or option_summary.get("median_spread_pct"))
    atm_spread = _decimal(option_summary.get("columns", {}).get("atm_spread_pct") or option_summary.get("atm_spread_pct"))
    if liquidity_score is not None and liquidity_score < 50:
        messages.append(f"low_option_liquidity_score:{liquidity_score}")
    if median_spread is not None and median_spread > 35:
        messages.append(f"wide_chain_median_spread_pct:{median_spread}")
    if atm_spread is not None and atm_spread > 25:
        messages.append(f"wide_atm_spread_pct:{atm_spread}")
    return messages


def _listed_contract_index(option_summary: dict[str, Any]) -> set[tuple[str, date, Decimal]]:
    candidates = option_summary.get("tradable_candidates")
    if candidates is None:
        candidates = (option_summary.get("summary_json") or {}).get("tradable_candidates")
    out = set()
    for group in (candidates or {}).values():
        for side_name, payload in (group or {}).items():
            if not payload:
                continue
            option_type = "CALL" if side_name.lower() == "call" else "PUT"
            expiry = _parse_day(payload.get("expiry"))
            strike = _decimal(payload.get("strike"))
            if expiry and strike:
                out.add((option_type, expiry, strike))
    return out


def _parse_day(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    text = str(value)
    try:
        if len(text) == 8 and text.isdigit():
            return datetime.strptime(text, "%Y%m%d").date()
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
