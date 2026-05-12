"""Position valuation and exit-plan suggestions for paper option batches."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import math
from typing import Any

import requests

from broker.moomoo import MoomooClient
from utils.config import config
from utils.db import (
    PaperOptionExitPlan,
    PaperOptionOrderBatch,
    PaperOptionOrderBatchLeg,
    PaperOptionPositionSnapshot,
    SessionLocal,
)

CONTRACT_MULTIPLIER = Decimal("100")
DEFAULT_TAKE_PROFIT_PCT = Decimal("50")
DEFAULT_STOP_LOSS_PCT = Decimal("-50")
DEFAULT_EXPIRY_WARN_DAYS = 1


def refresh_open_positions(
    *,
    take_profit_pct: Decimal | float | str = DEFAULT_TAKE_PROFIT_PCT,
    stop_loss_pct: Decimal | float | str = DEFAULT_STOP_LOSS_PCT,
    notify: bool = False,
) -> dict[str, Any]:
    """Refresh all filled paper option batches that have not been closed."""
    db = SessionLocal()
    try:
        batches = (
            db.query(PaperOptionOrderBatch)
            .filter(PaperOptionOrderBatch.status.in_(("filled", "partial_filled")))
            .order_by(PaperOptionOrderBatch.id.asc())
            .all()
        )
        batch_ids = [batch.id for batch in batches]
    finally:
        db.close()

    results = []
    errors = []
    for batch_id in batch_ids:
        try:
            results.append(
                refresh_position_snapshot(
                    order_batch_id=batch_id,
                    take_profit_pct=take_profit_pct,
                    stop_loss_pct=stop_loss_pct,
                    notify=notify,
                )
            )
        except Exception as exc:
            errors.append({"order_batch_id": batch_id, "error": str(exc)})
    return {
        "batch_count": len(batch_ids),
        "refreshed_count": len(results),
        "error_count": len(errors),
        "results": results,
        "errors": errors,
    }


def refresh_position_snapshot(
    *,
    order_batch_id: int,
    take_profit_pct: Decimal | float | str = DEFAULT_TAKE_PROFIT_PCT,
    stop_loss_pct: Decimal | float | str = DEFAULT_STOP_LOSS_PCT,
    notify: bool = False,
) -> dict[str, Any]:
    """Value a filled paper option batch and create an exit-plan suggestion."""
    db = SessionLocal()
    moomoo = MoomooClient()
    try:
        batch = db.query(PaperOptionOrderBatch).filter(PaperOptionOrderBatch.id == order_batch_id).first()
        if batch is None:
            raise ValueError(f"order batch {order_batch_id} not found")
        if batch.status not in {"filled", "partial_filled"}:
            raise ValueError(f"order batch {order_batch_id} status is {batch.status}, not a filled position")
        legs = (
            db.query(PaperOptionOrderBatchLeg)
            .filter(PaperOptionOrderBatchLeg.order_batch_id == batch.id)
            .order_by(PaperOptionOrderBatchLeg.leg_index.asc())
            .all()
        )
        if not legs:
            raise ValueError(f"order batch {order_batch_id} has no legs")

        quotes = _fetch_quotes(moomoo, legs)
        snapshot_payload = _snapshot_payload(batch, legs, quotes)
        snapshot = PaperOptionPositionSnapshot(**snapshot_payload)
        db.add(snapshot)
        db.flush()

        exit_payload = _exit_plan_payload(
            snapshot=snapshot,
            batch=batch,
            legs=legs,
            quotes=quotes,
            take_profit_pct=_decimal(take_profit_pct) or DEFAULT_TAKE_PROFIT_PCT,
            stop_loss_pct=_decimal(stop_loss_pct) or DEFAULT_STOP_LOSS_PCT,
        )
        exit_plan = PaperOptionExitPlan(**exit_payload)
        db.add(exit_plan)
        db.commit()

        result = {
            "order_batch_id": batch.id,
            "position_snapshot_id": snapshot.id,
            "exit_plan_id": exit_plan.id,
            "ticker": batch.ticker,
            "entry_net_debit": str(snapshot.entry_net_debit),
            "current_exit_value": str(snapshot.current_exit_value),
            "unrealized_pl": str(snapshot.unrealized_pl),
            "unrealized_pl_pct": str(snapshot.unrealized_pl_pct),
            "exit_action": exit_plan.action,
            "exit_status": exit_plan.status,
            "reasons": exit_plan.reason_json,
        }
        if notify:
            _send_telegram_notification(result)
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        moomoo.close()
        db.close()


def _fetch_quotes(moomoo: MoomooClient, legs: list[PaperOptionOrderBatchLeg]) -> dict[int, dict[str, Any]]:
    data = moomoo.market_snapshot([leg.broker_code for leg in legs])
    rows = {}
    if data.empty:
        return rows
    by_code = {str(row["code"]): row.to_dict() for _, row in data.iterrows()}
    for leg in legs:
        rows[leg.id] = by_code.get(leg.broker_code, {})
    return rows


def _snapshot_payload(
    batch: PaperOptionOrderBatch,
    legs: list[PaperOptionOrderBatchLeg],
    quotes: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    entry = Decimal("0")
    current = Decimal("0")
    max_profit = None
    max_loss = Decimal("0")
    quote_rows = []
    strikes = []

    for leg in legs:
        qty = _decimal(leg.dealt_qty) or Decimal(str(leg.quantity or 0))
        avg = _decimal(leg.dealt_avg_price) or Decimal("0")
        sign = Decimal("1") if leg.action == "BUY" else Decimal("-1")
        entry += sign * avg * qty * CONTRACT_MULTIPLIER

        quote = quotes.get(leg.id) or {}
        bid = _decimal(quote.get("bid_price"))
        ask = _decimal(quote.get("ask_price"))
        exit_price = bid if leg.action == "BUY" else ask
        if exit_price is not None:
            current += sign * exit_price * qty * CONTRACT_MULTIPLIER
        quote_rows.append(_leg_quote_payload(leg, quote, exit_price))
        strikes.append(_decimal(leg.strike) or Decimal("0"))

    if len(legs) == 2 and len({leg.option_type for leg in legs}) == 1:
        width = abs(strikes[0] - strikes[1]) * CONTRACT_MULTIPLIER * Decimal(str(legs[0].quantity))
        max_profit = max(width - max(entry, Decimal("0")), Decimal("0"))
        max_loss = max(entry, Decimal("0"))

    pl = current - entry
    pl_pct = (pl / entry * Decimal("100")) if entry > 0 else None
    return {
        "order_batch_id": batch.id,
        "strategy_run_id": batch.strategy_run_id,
        "ticker": batch.ticker,
        "status": "open",
        "entry_net_debit": entry,
        "current_exit_value": current,
        "unrealized_pl": pl,
        "unrealized_pl_pct": pl_pct,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "quote_json": quote_rows,
    }


def _exit_plan_payload(
    *,
    snapshot: PaperOptionPositionSnapshot,
    batch: PaperOptionOrderBatch,
    legs: list[PaperOptionOrderBatchLeg],
    quotes: dict[int, dict[str, Any]],
    take_profit_pct: Decimal,
    stop_loss_pct: Decimal,
) -> dict[str, Any]:
    reasons = []
    action = "hold"
    status = "monitor"
    pl_pct = _decimal(snapshot.unrealized_pl_pct)
    if pl_pct is not None and pl_pct >= take_profit_pct:
        action = "take_profit"
        status = "exit_recommended"
        reasons.append(f"take_profit_hit:{pl_pct}>={take_profit_pct}")
    elif pl_pct is not None and pl_pct <= stop_loss_pct:
        action = "stop_loss"
        status = "exit_recommended"
        reasons.append(f"stop_loss_hit:{pl_pct}<={stop_loss_pct}")

    min_days_to_expiry = min((leg.expiry - date.today()).days for leg in legs)
    if min_days_to_expiry <= DEFAULT_EXPIRY_WARN_DAYS:
        reasons.append(f"near_expiry_days:{min_days_to_expiry}")
        if status == "monitor":
            action = "review_near_expiry"
            status = "review"

    exit_legs = [_exit_leg(leg, quotes.get(leg.id) or {}) for leg in legs]
    return {
        "position_snapshot_id": snapshot.id,
        "order_batch_id": batch.id,
        "strategy_run_id": batch.strategy_run_id,
        "ticker": batch.ticker,
        "action": action,
        "status": status,
        "reason_json": reasons,
        "exit_legs_json": exit_legs,
    }


def _exit_leg(leg: PaperOptionOrderBatchLeg, quote: dict[str, Any]) -> dict[str, Any]:
    close_action = "SELL" if leg.action == "BUY" else "BUY"
    limit_price = quote.get("bid_price") if close_action == "SELL" else quote.get("ask_price")
    return {
        "batch_leg_id": leg.id,
        "action": close_action,
        "quantity": int(leg.dealt_qty or leg.quantity),
        "broker_code": leg.broker_code,
        "suggested_limit_price": limit_price,
        "pricing_basis": "bid_for_sell_ask_for_buy",
    }


def _leg_quote_payload(leg: PaperOptionOrderBatchLeg, quote: dict[str, Any], exit_price: Decimal | None) -> dict[str, Any]:
    return {
        "batch_leg_id": leg.id,
        "broker_code": leg.broker_code,
        "action": leg.action,
        "quantity": int(leg.dealt_qty or leg.quantity),
        "entry_price": _float(leg.dealt_avg_price),
        "bid_price": _float(quote.get("bid_price")),
        "ask_price": _float(quote.get("ask_price")),
        "last_price": _float(quote.get("last_price")),
        "exit_price": _float(exit_price),
        "raw": _jsonable(quote),
    }


def _send_telegram_notification(result: dict[str, Any]) -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TARGET_GROUP_ID:
        return
    text = (
        "<b>Paper option position update</b>\n"
        f"batch <code>{result['order_batch_id']}</code> <b>{result['ticker']}</b>\n"
        f"P/L <code>{result['unrealized_pl']}</code> "
        f"(<code>{result['unrealized_pl_pct']}%</code>)\n"
        f"exit: <code>{result['exit_action']}</code> / <code>{result['exit_status']}</code>"
    )
    requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": config.TARGET_GROUP_ID, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )


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


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for key, value in row.items():
        if hasattr(value, "item"):
            value = value.item()
        if isinstance(value, float) and math.isnan(value):
            value = None
        if isinstance(value, Decimal):
            value = float(value)
        out[key] = value
    return out
