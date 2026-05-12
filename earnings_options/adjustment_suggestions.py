"""Suggest safer adjusted paper orders from pre-trade execution plans."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Any

from utils.db import PaperOptionAdjustmentSuggestion, PaperOptionExecutionPlan, SessionLocal

CONTRACT_MULTIPLIER = Decimal("100")
DEFAULT_MAX_SPREAD_PCT = Decimal("35")


def build_adjustment_suggestions(
    *,
    strategy_run_id: int,
    max_spread_pct: Decimal | float | str = DEFAULT_MAX_SPREAD_PCT,
) -> dict[str, Any]:
    """Create one adjustment suggestion per latest execution plan."""
    db = SessionLocal()
    try:
        plans = _latest_plans(db, strategy_run_id)
        if not plans:
            raise ValueError(f"No execution plans found for strategy_run_id={strategy_run_id}")

        spread_limit = _decimal(max_spread_pct) or DEFAULT_MAX_SPREAD_PCT
        suggestions = []
        for plan in plans:
            suggestion = PaperOptionAdjustmentSuggestion(**_suggestion_payload(plan, spread_limit))
            db.add(suggestion)
            suggestions.append(suggestion)
        db.commit()
        return {
            "strategy_run_id": strategy_run_id,
            "suggestion_count": len(suggestions),
            "statuses": _status_counts(suggestions),
            "recommendations": _recommendation_counts(suggestions),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _latest_plans(db, strategy_run_id: int) -> list[PaperOptionExecutionPlan]:
    rows = (
        db.query(PaperOptionExecutionPlan)
        .filter(PaperOptionExecutionPlan.strategy_run_id == strategy_run_id)
        .order_by(PaperOptionExecutionPlan.strategy_index.asc(), PaperOptionExecutionPlan.id.desc())
        .all()
    )
    latest = {}
    for row in rows:
        latest.setdefault(row.strategy_index, row)
    return list(latest.values())


def _suggestion_payload(plan: PaperOptionExecutionPlan, spread_limit: Decimal) -> dict[str, Any]:
    reasons = []
    budget = _decimal(plan.max_budget_to_use)
    current_debit = _decimal(plan.conservative_net_debit) or Decimal("0")
    max_spread = _decimal(plan.max_spread_pct) or Decimal("0")
    original_qty = _original_quantity(plan)
    unit_debit = _unit_debit(plan)
    suggested_qty = original_qty

    if not plan.structure_ok:
        reasons.append("structure_not_ok")
    if not plan.quote_fresh_ok:
        reasons.append("quote_not_fresh")
    if not plan.liquidity_ok or max_spread > spread_limit:
        reasons.append(f"liquidity_not_ok:max_spread_pct={max_spread}")

    recommendation = "use_original"
    status = "ready_for_paper_order" if plan.status == "ready_for_paper_order" else "needs_review"

    if budget is None or budget <= 0:
        reasons.append("missing_budget_limit")
        recommendation = "skip"
        status = "not_recommended"
        suggested_qty = 0
    elif reasons:
        recommendation = "skip" if any("liquidity_not_ok" in reason for reason in reasons) else "needs_manual_review"
        status = "not_recommended" if recommendation == "skip" else "needs_review"
        if recommendation == "skip":
            suggested_qty = 0
    elif current_debit > budget:
        if unit_debit is None or unit_debit <= 0:
            reasons.append("cannot_scale_quantity")
            recommendation = "skip"
            status = "not_recommended"
            suggested_qty = 0
        else:
            suggested_qty = int((budget / unit_debit).to_integral_value(rounding=ROUND_FLOOR))
            if suggested_qty >= 1:
                reasons.append(f"reduce_quantity_to_fit_budget:{original_qty}->{suggested_qty}")
                recommendation = "reduce_quantity"
                status = "ready_after_adjustment"
            else:
                reasons.append("budget_too_small_for_one_contract")
                recommendation = "skip"
                status = "not_recommended"
                suggested_qty = 0

    suggested_debit = (unit_debit or Decimal("0")) * Decimal(str(suggested_qty))
    suggested_legs = _suggested_legs(plan, suggested_qty)
    return {
        "execution_plan_id": plan.id,
        "strategy_run_id": plan.strategy_run_id,
        "ticker": plan.ticker,
        "report_date": plan.report_date,
        "strategy_index": plan.strategy_index,
        "strategy_name": plan.strategy_name,
        "status": status,
        "recommendation": recommendation,
        "original_quantity": original_qty,
        "suggested_quantity": suggested_qty,
        "original_conservative_debit": current_debit,
        "suggested_conservative_debit": suggested_debit,
        "budget_limit": budget,
        "max_spread_pct": max_spread,
        "reason_json": reasons,
        "suggested_legs_json": suggested_legs,
    }


def _original_quantity(plan: PaperOptionExecutionPlan) -> int:
    legs = plan.legs_json or []
    quantities = [int(leg.get("quantity") or 0) for leg in legs]
    return min(quantities) if quantities else 0


def _unit_debit(plan: PaperOptionExecutionPlan) -> Decimal | None:
    qty = _original_quantity(plan)
    debit = _decimal(plan.conservative_net_debit)
    if qty <= 0 or debit is None:
        return None
    return debit / Decimal(str(qty))


def _suggested_legs(plan: PaperOptionExecutionPlan, suggested_qty: int) -> list[dict[str, Any]]:
    legs = []
    for leg in plan.legs_json or []:
        quote = leg.get("latest_quote") or {}
        action = leg.get("action")
        if action == "BUY":
            suggested_limit = quote.get("ask_price")
        elif action == "SELL":
            suggested_limit = quote.get("bid_price")
        else:
            suggested_limit = leg.get("limit_price_hint")
        legs.append(
            {
                "draft_id": leg.get("draft_id"),
                "action": action,
                "option_type": leg.get("option_type"),
                "expiry": leg.get("expiry"),
                "strike": leg.get("strike"),
                "broker_code": leg.get("broker_code"),
                "occ_symbol": leg.get("occ_symbol"),
                "quantity": suggested_qty,
                "suggested_limit_price": suggested_limit,
                "pricing_basis": "ask_for_buy_bid_for_sell",
            }
        )
    return legs


def _status_counts(suggestions: list[PaperOptionAdjustmentSuggestion]) -> dict[str, int]:
    counts = {}
    for item in suggestions:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


def _recommendation_counts(suggestions: list[PaperOptionAdjustmentSuggestion]) -> dict[str, int]:
    counts = {}
    for item in suggestions:
        counts[item.recommendation] = counts.get(item.recommendation, 0) + 1
    return counts


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
