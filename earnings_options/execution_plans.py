"""Pre-trade risk checks and execution plans for paper option drafts."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from utils.db import (
    PaperOptionExecutionPlan,
    PaperOptionOrderDraft,
    PaperOptionQuoteSnapshot,
    SessionLocal,
)

CONTRACT_MULTIPLIER = Decimal("100")
DEFAULT_MAX_SPREAD_PCT = Decimal("35")
DEFAULT_MAX_QUOTE_AGE_MINUTES = Decimal("20")


def build_execution_plans(
    *,
    strategy_run_id: int,
    total_budget: Decimal | float | str | None = None,
    max_spread_pct: Decimal | float | str = DEFAULT_MAX_SPREAD_PCT,
    max_quote_age_minutes: Decimal | float | str = DEFAULT_MAX_QUOTE_AGE_MINUTES,
) -> dict[str, Any]:
    """Create one pre-trade execution plan per strategy.

    This is analysis only. It does not call broker APIs and does not place orders.
    """
    db = SessionLocal()
    try:
        drafts = (
            db.query(PaperOptionOrderDraft)
            .filter(PaperOptionOrderDraft.strategy_run_id == strategy_run_id)
            .order_by(PaperOptionOrderDraft.strategy_index.asc(), PaperOptionOrderDraft.leg_index.asc())
            .all()
        )
        if not drafts:
            raise ValueError(f"No paper option order drafts found for strategy_run_id={strategy_run_id}")

        budget = _decimal(total_budget)
        spread_limit = _decimal(max_spread_pct) or DEFAULT_MAX_SPREAD_PCT
        age_limit = _decimal(max_quote_age_minutes) or DEFAULT_MAX_QUOTE_AGE_MINUTES

        groups: dict[int, list[PaperOptionOrderDraft]] = defaultdict(list)
        for draft in drafts:
            groups[draft.strategy_index].append(draft)

        plans = []
        for strategy_index, legs in groups.items():
            plan_payload = _plan_for_strategy(
                db=db,
                legs=legs,
                budget=budget,
                spread_limit=spread_limit,
                age_limit=age_limit,
            )
            plan = PaperOptionExecutionPlan(**plan_payload)
            db.add(plan)
            plans.append(plan)

        db.commit()
        return {
            "strategy_run_id": strategy_run_id,
            "plan_count": len(plans),
            "statuses": _status_counts(plans),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _plan_for_strategy(
    *,
    db,
    legs: list[PaperOptionOrderDraft],
    budget: Decimal | None,
    spread_limit: Decimal,
    age_limit: Decimal,
) -> dict[str, Any]:
    first = legs[0]
    leg_payloads = []
    messages = []
    mid_debit = Decimal("0")
    conservative_debit = Decimal("0")
    max_spread_pct = Decimal("0")
    max_age_minutes = Decimal("0")

    for leg in legs:
        quote = _latest_quote(db, leg.id)
        leg_messages = []
        if leg.validation_status != "broker_mapped" or not leg.broker_code:
            leg_messages.append("draft_not_broker_mapped")
        if quote is None:
            leg_messages.append("missing_quote_snapshot")
        else:
            bid = _decimal(quote.bid_price)
            ask = _decimal(quote.ask_price)
            mid = _decimal(quote.mid_price)
            if bid is None or ask is None or bid <= 0 or ask <= 0:
                leg_messages.append("invalid_bid_ask")
            if mid is None or mid <= 0:
                leg_messages.append("invalid_mid_price")

            spread_pct = _spread_pct(bid, ask, mid)
            age = _quote_age_minutes(quote)
            if spread_pct is not None:
                max_spread_pct = max(max_spread_pct, spread_pct)
                if spread_pct > spread_limit:
                    leg_messages.append(f"wide_spread_pct:{spread_pct}")
            else:
                leg_messages.append("missing_spread_pct")
            if age is not None:
                max_age_minutes = max(max_age_minutes, age)
                if age > age_limit:
                    leg_messages.append(f"stale_quote_minutes:{age}")
            else:
                leg_messages.append("missing_quote_age")

            qty = Decimal(str(leg.quantity or 0))
            sign = Decimal("1") if leg.action == "BUY" else Decimal("-1")
            if mid is not None:
                mid_debit += sign * mid * qty * CONTRACT_MULTIPLIER
            conservative_price = ask if leg.action == "BUY" else bid
            if conservative_price is not None:
                conservative_debit += sign * conservative_price * qty * CONTRACT_MULTIPLIER

        messages.extend([f"leg_{leg.leg_index}:{msg}" for msg in leg_messages])
        leg_payloads.append(_leg_payload(leg, quote, leg_messages))

    structure_messages = _structure_messages(legs)
    messages.extend(structure_messages)
    structure_ok = not structure_messages
    liquidity_ok = not any(
        "wide_spread_pct" in msg or "invalid_bid_ask" in msg or "missing_spread_pct" in msg
        for msg in messages
    )
    quote_fresh_ok = not any("stale_quote" in msg or "missing_quote" in msg for msg in messages)
    budget_limit = _budget_limit(legs, budget)
    estimated_max_loss = max(conservative_debit, Decimal("0"))
    budget_ok = budget_limit is not None and estimated_max_loss <= budget_limit
    if budget_limit is None:
        messages.append("missing_budget_limit")
    elif not budget_ok:
        messages.append(f"budget_exceeded:{estimated_max_loss}>{budget_limit}")

    status = "ready_for_paper_order" if structure_ok and liquidity_ok and quote_fresh_ok and budget_ok else "needs_review"
    return {
        "strategy_run_id": first.strategy_run_id,
        "ticker": first.ticker,
        "report_date": first.report_date,
        "strategy_index": first.strategy_index,
        "strategy_name": first.strategy_name,
        "scenario": first.scenario,
        "status": status,
        "estimated_mid_debit": mid_debit,
        "conservative_net_debit": conservative_debit,
        "estimated_max_loss": estimated_max_loss,
        "max_budget_to_use": budget_limit,
        "budget_ok": budget_ok,
        "liquidity_ok": liquidity_ok,
        "quote_fresh_ok": quote_fresh_ok,
        "structure_ok": structure_ok,
        "max_spread_pct": max_spread_pct,
        "max_quote_age_minutes": max_age_minutes,
        "legs_json": leg_payloads,
        "checks_json": {
            "messages": messages,
            "spread_limit_pct": float(spread_limit),
            "quote_age_limit_minutes": float(age_limit),
            "contract_multiplier": int(CONTRACT_MULTIPLIER),
            "pricing_method": "BUY uses ask, SELL uses bid for conservative debit; mid debit uses mid prices",
        },
    }


def _latest_quote(db, draft_id: int) -> PaperOptionQuoteSnapshot | None:
    return (
        db.query(PaperOptionQuoteSnapshot)
        .filter(PaperOptionQuoteSnapshot.order_draft_id == draft_id)
        .order_by(PaperOptionQuoteSnapshot.id.desc())
        .first()
    )


def _structure_messages(legs: list[PaperOptionOrderDraft]) -> list[str]:
    messages = []
    expiries = {leg.expiry for leg in legs}
    if len(expiries) != 1:
        messages.append("mixed_expiries")
    quantities = {leg.quantity for leg in legs}
    if len(legs) > 1 and len(quantities) != 1:
        messages.append("mixed_quantities")
    if any(leg.action not in {"BUY", "SELL"} for leg in legs):
        messages.append("invalid_leg_action")
    if any(leg.option_type not in {"CALL", "PUT"} for leg in legs):
        messages.append("invalid_leg_option_type")
    if len(legs) > 4:
        messages.append("too_many_legs_for_first_execution_version")
    return messages


def _budget_limit(legs: list[PaperOptionOrderDraft], total_budget: Decimal | None) -> Decimal | None:
    strategy_budget = _decimal(legs[0].max_budget_to_use)
    if strategy_budget is not None and strategy_budget > 0:
        return strategy_budget
    return total_budget


def _leg_payload(leg: PaperOptionOrderDraft, quote: PaperOptionQuoteSnapshot | None, messages: list[str]) -> dict[str, Any]:
    return {
        "draft_id": leg.id,
        "leg_index": leg.leg_index,
        "action": leg.action,
        "option_type": leg.option_type,
        "expiry": leg.expiry.isoformat(),
        "strike": float(leg.strike),
        "quantity": leg.quantity,
        "occ_symbol": leg.occ_symbol,
        "broker_code": leg.broker_code,
        "limit_price_hint": _float(leg.limit_price_hint),
        "latest_quote": _quote_payload(quote),
        "messages": messages,
    }


def _quote_payload(quote: PaperOptionQuoteSnapshot | None) -> dict[str, Any] | None:
    if quote is None:
        return None
    return {
        "quote_snapshot_id": quote.id,
        "quote_time": quote.quote_time.isoformat() if quote.quote_time else None,
        "created_at": quote.created_at.isoformat() if quote.created_at else None,
        "last_price": _float(quote.last_price),
        "bid_price": _float(quote.bid_price),
        "ask_price": _float(quote.ask_price),
        "mid_price": _float(quote.mid_price),
        "volume": _float(quote.volume),
        "open_interest": _float(quote.open_interest),
        "implied_volatility": _float(quote.implied_volatility),
        "delta": _float(quote.delta),
    }


def _spread_pct(bid: Decimal | None, ask: Decimal | None, mid: Decimal | None) -> Decimal | None:
    if bid is None or ask is None or mid is None or mid <= 0:
        return None
    return (ask - bid) / mid * Decimal("100")


def _quote_age_minutes(quote: PaperOptionQuoteSnapshot) -> Decimal | None:
    created_at = quote.created_at
    if created_at is None:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return Decimal(str((datetime.now(timezone.utc) - created_at.astimezone(timezone.utc)).total_seconds() / 60))


def _status_counts(plans: list[PaperOptionExecutionPlan]) -> dict[str, int]:
    counts = {}
    for plan in plans:
        counts[plan.status] = counts.get(plan.status, 0) + 1
    return counts


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _float(value: Any) -> float | None:
    dec = _decimal(value)
    return float(dec) if dec is not None else None
