"""Stage approved adjustment suggestions as paper option order batches."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from utils.db import (
    PaperOptionAdjustmentSuggestion,
    PaperOptionManualApproval,
    PaperOptionOrderBatch,
    PaperOptionOrderBatchLeg,
    SessionLocal,
)


class OrderBatchError(RuntimeError):
    pass


def stage_order_batch_from_approval(*, approval_id: int) -> dict[str, Any]:
    """Convert one approved manual approval into a staged paper order batch.

    This writes local staging rows only. It does not call Moomoo.
    """
    db = SessionLocal()
    try:
        approval = (
            db.query(PaperOptionManualApproval)
            .filter(PaperOptionManualApproval.id == approval_id)
            .first()
        )
        if approval is None:
            raise OrderBatchError(f"approval {approval_id} not found")
        if approval.status != "approved":
            raise OrderBatchError(f"approval {approval_id} is {approval.status}, not approved")

        existing = (
            db.query(PaperOptionOrderBatch)
            .filter(PaperOptionOrderBatch.manual_approval_id == approval.id)
            .first()
        )
        if existing is not None:
            return {
                "order_batch_id": existing.id,
                "approval_id": approval.id,
                "status": existing.status,
                "created": False,
                "leg_count": db.query(PaperOptionOrderBatchLeg)
                .filter(PaperOptionOrderBatchLeg.order_batch_id == existing.id)
                .count(),
            }

        suggestion = (
            db.query(PaperOptionAdjustmentSuggestion)
            .filter(PaperOptionAdjustmentSuggestion.id == approval.adjustment_suggestion_id)
            .first()
        )
        if suggestion is None:
            raise OrderBatchError(f"suggestion {approval.adjustment_suggestion_id} not found")
        if suggestion.status not in {"ready_after_adjustment", "ready_for_paper_order"}:
            raise OrderBatchError(f"suggestion {suggestion.id} status is {suggestion.status}, not stageable")
        if not suggestion.suggested_quantity or suggestion.suggested_quantity <= 0:
            raise OrderBatchError(f"suggestion {suggestion.id} has no positive suggested quantity")

        legs = suggestion.suggested_legs_json or []
        _validate_legs(legs)
        batch = PaperOptionOrderBatch(
            manual_approval_id=approval.id,
            adjustment_suggestion_id=suggestion.id,
            strategy_run_id=suggestion.strategy_run_id,
            ticker=suggestion.ticker,
            report_date=suggestion.report_date,
            strategy_index=suggestion.strategy_index,
            strategy_name=suggestion.strategy_name,
            status="staged",
            estimated_cost=suggestion.suggested_conservative_debit,
            payload_json={
                "approval_id": approval.id,
                "suggestion_id": suggestion.id,
                "recommendation": suggestion.recommendation,
                "reasons": suggestion.reason_json,
                "created_from": "manual_approval",
            },
        )
        db.add(batch)
        db.flush()

        for index, leg in enumerate(legs, start=1):
            db.add(_batch_leg(batch.id, index, leg))
        db.commit()
        return {
            "order_batch_id": batch.id,
            "approval_id": approval.id,
            "status": batch.status,
            "created": True,
            "leg_count": len(legs),
            "estimated_cost": str(batch.estimated_cost),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _validate_legs(legs: list[dict[str, Any]]) -> None:
    if not legs:
        raise OrderBatchError("suggestion has no legs")
    for leg in legs:
        if int(leg.get("quantity") or 0) <= 0:
            raise OrderBatchError("leg quantity must be positive")
        if not leg.get("broker_code"):
            raise OrderBatchError("leg broker_code missing")
        if _decimal(leg.get("suggested_limit_price")) is None:
            raise OrderBatchError("leg suggested_limit_price missing")


def _batch_leg(batch_id: int, index: int, leg: dict[str, Any]) -> PaperOptionOrderBatchLeg:
    return PaperOptionOrderBatchLeg(
        order_batch_id=batch_id,
        draft_id=leg.get("draft_id"),
        leg_index=index,
        action=str(leg.get("action")).upper(),
        option_type=str(leg.get("option_type")).upper(),
        expiry=_parse_day(leg.get("expiry")),
        strike=_decimal(leg.get("strike")) or Decimal("0"),
        quantity=int(leg.get("quantity")),
        broker_code=str(leg.get("broker_code")),
        occ_symbol=leg.get("occ_symbol"),
        suggested_limit_price=_decimal(leg.get("suggested_limit_price")),
        order_type="limit",
        status="staged",
        payload_json=leg,
    )


def _parse_day(value: Any):
    if not value:
        raise OrderBatchError("expiry missing")
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
