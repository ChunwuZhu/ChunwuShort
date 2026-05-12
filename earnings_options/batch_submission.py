"""Submit staged paper option order batches to Moomoo paper trading."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func

from broker.moomoo_paper import MoomooPaperTrader
from utils.db import PaperOptionOrderBatch, PaperOptionOrderBatchLeg, SessionLocal


class BatchSubmissionError(RuntimeError):
    pass


def submit_paper_order_batch(
    *,
    order_batch_id: int,
    submit: bool = False,
    wait_seconds: int = 0,
) -> dict[str, Any]:
    """Dry-run or submit a staged paper order batch.

    When submit=False, this only returns the intended orders.
    """
    db = SessionLocal()
    trader = None
    try:
        batch = db.query(PaperOptionOrderBatch).filter(PaperOptionOrderBatch.id == order_batch_id).first()
        if batch is None:
            raise BatchSubmissionError(f"order batch {order_batch_id} not found")
        if batch.status not in {"staged", "partial_failed"}:
            raise BatchSubmissionError(f"order batch {order_batch_id} status is {batch.status}, not submit-ready")

        legs = (
            db.query(PaperOptionOrderBatchLeg)
            .filter(PaperOptionOrderBatchLeg.order_batch_id == batch.id)
            .order_by(PaperOptionOrderBatchLeg.leg_index.asc())
            .all()
        )
        _validate_batch_legs(legs)
        intended = [_intended_order(leg) for leg in legs]
        if not submit:
            return {
                "order_batch_id": batch.id,
                "mode": "dry_run",
                "status": batch.status,
                "orders": intended,
            }

        trader = MoomooPaperTrader()
        submitted = []
        failed = []
        for leg in legs:
            result = trader.limit_order(
                leg.broker_code,
                side=leg.action,
                qty=leg.quantity,
                price=float(leg.suggested_limit_price),
            )
            if result.ok:
                leg.status = "submitted"
                leg.broker_order_id = result.order_id
                submitted.append(
                    {
                        "leg_id": leg.id,
                        "broker_order_id": result.order_id,
                        "broker_code": leg.broker_code,
                    }
                )
                if wait_seconds and result.order_id:
                    trader.wait_for_order(result.order_id, timeout_sec=wait_seconds)
            else:
                leg.status = "submit_failed"
                failed.append(
                    {
                        "leg_id": leg.id,
                        "broker_code": leg.broker_code,
                        "message": result.message,
                    }
                )

        batch.status = "submitted" if not failed else ("partial_failed" if submitted else "submit_failed")
        batch.submitted_at = func.now()
        db.commit()
        return {
            "order_batch_id": batch.id,
            "mode": "submit",
            "status": batch.status,
            "submitted": submitted,
            "failed": failed,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        if trader is not None:
            trader.close()
        db.close()


def _validate_batch_legs(legs: list[PaperOptionOrderBatchLeg]) -> None:
    if not legs:
        raise BatchSubmissionError("order batch has no legs")
    for leg in legs:
        if leg.status not in {"staged", "submit_failed"}:
            raise BatchSubmissionError(f"leg {leg.id} status is {leg.status}, not submit-ready")
        if leg.action not in {"BUY", "SELL"}:
            raise BatchSubmissionError(f"leg {leg.id} has invalid action {leg.action}")
        if not leg.broker_code:
            raise BatchSubmissionError(f"leg {leg.id} broker_code missing")
        if not leg.quantity or leg.quantity <= 0:
            raise BatchSubmissionError(f"leg {leg.id} quantity must be positive")
        if leg.suggested_limit_price is None or leg.suggested_limit_price <= 0:
            raise BatchSubmissionError(f"leg {leg.id} limit price must be positive")


def _intended_order(leg: PaperOptionOrderBatchLeg) -> dict[str, Any]:
    return {
        "leg_id": leg.id,
        "leg_index": leg.leg_index,
        "action": leg.action,
        "broker_code": leg.broker_code,
        "quantity": leg.quantity,
        "limit_price": str(leg.suggested_limit_price),
        "order_type": leg.order_type,
        "status": leg.status,
    }
