"""Submit and monitor paper option exit order batches."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
from typing import Any

import requests
from sqlalchemy import func

from broker.moomoo_paper import MoomooPaperTrader
from utils.config import config
from utils.db import (
    PaperOptionExitOrderBatch,
    PaperOptionExitOrderBatchLeg,
    PaperOptionOrderBatch,
    SessionLocal,
)


class ExitBatchSubmissionError(RuntimeError):
    pass


def submit_exit_order_batch(
    *,
    exit_order_batch_id: int,
    submit: bool = False,
    wait_seconds: int = 0,
) -> dict[str, Any]:
    db = SessionLocal()
    trader = None
    try:
        batch = db.query(PaperOptionExitOrderBatch).filter(PaperOptionExitOrderBatch.id == exit_order_batch_id).first()
        if batch is None:
            raise ExitBatchSubmissionError(f"exit order batch {exit_order_batch_id} not found")
        if batch.status not in {"staged", "partial_failed", "submit_failed", "attention_required"}:
            raise ExitBatchSubmissionError(f"exit order batch {exit_order_batch_id} status is {batch.status}")
        legs = _legs(db, batch.id)
        _validate_submit_legs(legs)
        intended = [_intended_order(leg) for leg in legs]
        if not submit:
            return {"exit_order_batch_id": batch.id, "mode": "dry_run", "status": batch.status, "orders": intended}

        trader = MoomooPaperTrader()
        submitted = []
        failed = []
        for leg in _submittable_legs(legs):
            result = trader.limit_order(
                leg.broker_code,
                side=leg.action,
                qty=leg.quantity,
                price=float(leg.suggested_limit_price),
            )
            if result.ok:
                leg.status = "submitted"
                leg.broker_order_id = result.order_id
                submitted.append({"leg_id": leg.id, "broker_order_id": result.order_id, "broker_code": leg.broker_code})
                if wait_seconds and result.order_id:
                    trader.wait_for_order(result.order_id, timeout_sec=wait_seconds)
            else:
                leg.status = "submit_failed"
                failed.append({"leg_id": leg.id, "broker_code": leg.broker_code, "message": result.message})

        batch.status = _submission_batch_status(legs)
        batch.submitted_at = func.now()
        db.commit()
        return {
            "exit_order_batch_id": batch.id,
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


def refresh_exit_order_batch_status(*, exit_order_batch_id: int, notify: bool = False) -> dict[str, Any]:
    db = SessionLocal()
    trader = MoomooPaperTrader()
    try:
        batch = db.query(PaperOptionExitOrderBatch).filter(PaperOptionExitOrderBatch.id == exit_order_batch_id).first()
        if batch is None:
            raise ExitBatchSubmissionError(f"exit order batch {exit_order_batch_id} not found")
        legs = _legs(db, batch.id)
        changed = []
        for leg in legs:
            if not leg.broker_order_id:
                continue
            old_status = leg.status
            data = trader.orders(leg.broker_order_id)
            if data is None or data.empty:
                continue
            row = data.iloc[0].to_dict()
            _apply_order_row(leg, row)
            if old_status != leg.status:
                changed.append(_event_payload(batch, leg, old_status))
        batch.status = _batch_status(legs)
        if batch.status == "filled":
            source = db.query(PaperOptionOrderBatch).filter(PaperOptionOrderBatch.id == batch.source_order_batch_id).first()
            if source is not None:
                source.status = "closed"
        db.commit()
        if notify and changed:
            _send_telegram_notification(changed)
        return {"exit_order_batch_id": batch.id, "status": batch.status, "changed": changed}
    except Exception:
        db.rollback()
        raise
    finally:
        trader.close()
        db.close()


def _legs(db, batch_id: int) -> list[PaperOptionExitOrderBatchLeg]:
    return (
        db.query(PaperOptionExitOrderBatchLeg)
        .filter(PaperOptionExitOrderBatchLeg.exit_order_batch_id == batch_id)
        .order_by(PaperOptionExitOrderBatchLeg.leg_index.asc())
        .all()
    )


def _validate_submit_legs(legs: list[PaperOptionExitOrderBatchLeg]) -> None:
    if not legs:
        raise ExitBatchSubmissionError("exit order batch has no legs")
    if not _submittable_legs(legs):
        raise ExitBatchSubmissionError("exit order batch has no staged or failed legs to submit")
    for leg in legs:
        if leg.status not in {"staged", "submit_failed", "submitted", "partial_filled", "filled"}:
            raise ExitBatchSubmissionError(f"exit leg {leg.id} status is {leg.status}")
        if leg.status not in {"staged", "submit_failed"}:
            continue
        if leg.action not in {"BUY", "SELL"}:
            raise ExitBatchSubmissionError(f"exit leg {leg.id} has invalid action {leg.action}")
        if not leg.broker_code:
            raise ExitBatchSubmissionError(f"exit leg {leg.id} broker_code missing")
        if not leg.quantity or leg.quantity <= 0:
            raise ExitBatchSubmissionError(f"exit leg {leg.id} quantity must be positive")
        if leg.suggested_limit_price is None or leg.suggested_limit_price <= 0:
            raise ExitBatchSubmissionError(f"exit leg {leg.id} limit price must be positive")


def _submittable_legs(legs: list[PaperOptionExitOrderBatchLeg]) -> list[PaperOptionExitOrderBatchLeg]:
    return [leg for leg in legs if leg.status in {"staged", "submit_failed"}]


def _submission_batch_status(legs: list[PaperOptionExitOrderBatchLeg]) -> str:
    statuses = {leg.status for leg in legs}
    if any(status == "submit_failed" for status in statuses):
        return "partial_failed" if any(status in {"submitted", "partial_filled", "filled"} for status in statuses) else "submit_failed"
    if any(status == "staged" for status in statuses):
        return "partial_failed"
    if statuses == {"filled"}:
        return "filled"
    if any(status == "partial_filled" for status in statuses) or any(status == "filled" for status in statuses):
        return "partial_filled"
    if statuses == {"submitted"}:
        return "submitted"
    return "attention_required"


def _intended_order(leg: PaperOptionExitOrderBatchLeg) -> dict[str, Any]:
    return {
        "leg_id": leg.id,
        "leg_index": leg.leg_index,
        "action": leg.action,
        "broker_code": leg.broker_code,
        "quantity": leg.quantity,
        "limit_price": str(leg.suggested_limit_price),
        "status": leg.status,
    }


def _apply_order_row(leg: PaperOptionExitOrderBatchLeg, row: dict[str, Any]) -> None:
    leg.status = _normalize_order_status(str(row.get("order_status") or ""))
    leg.dealt_qty = _decimal(row.get("dealt_qty"))
    leg.dealt_avg_price = _decimal(row.get("dealt_avg_price"))
    leg.last_err_msg = str(row.get("last_err_msg") or "") or None
    leg.last_status_at = func.now()
    payload = dict(leg.payload_json or {})
    payload["latest_broker_order"] = _jsonable(row)
    leg.payload_json = payload


def _normalize_order_status(status: str) -> str:
    status = status.upper()
    if status == "FILLED_ALL":
        return "filled"
    if status == "FILLED_PART":
        return "partial_filled"
    if status in {"CANCELLED_ALL", "CANCELLED_PART", "FILLCANCELLED"}:
        return "cancelled"
    if status in {"FAILED", "SUBMIT_FAILED", "TIMEOUT"}:
        return "failed"
    if status in {"DISABLED"}:
        return "disabled"
    if status in {"DELETED"}:
        return "deleted"
    if status in {"SUBMITTED", "SUBMITTING", "WAITING_SUBMIT"}:
        return "submitted"
    return status.lower() or "unknown"


def _batch_status(legs: list[PaperOptionExitOrderBatchLeg]) -> str:
    statuses = {leg.status for leg in legs}
    if statuses == {"filled"}:
        return "filled"
    if any(status in {"failed", "disabled", "deleted"} for status in statuses):
        return "attention_required"
    if any(status == "cancelled" for status in statuses):
        return "cancelled" if statuses == {"cancelled"} else "attention_required"
    if any(status == "partial_filled" for status in statuses) or any(status == "filled" for status in statuses):
        return "partial_filled"
    if statuses == {"submitted"}:
        return "submitted"
    return "attention_required"


def _event_payload(
    batch: PaperOptionExitOrderBatch,
    leg: PaperOptionExitOrderBatchLeg,
    old_status: str,
) -> dict[str, Any]:
    return {
        "exit_order_batch_id": batch.id,
        "source_order_batch_id": batch.source_order_batch_id,
        "ticker": batch.ticker,
        "leg_id": leg.id,
        "leg_index": leg.leg_index,
        "broker_order_id": leg.broker_order_id,
        "broker_code": leg.broker_code,
        "old_status": old_status,
        "new_status": leg.status,
        "dealt_qty": str(leg.dealt_qty) if leg.dealt_qty is not None else None,
        "dealt_avg_price": str(leg.dealt_avg_price) if leg.dealt_avg_price is not None else None,
    }


def _send_telegram_notification(events: list[dict[str, Any]]) -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TARGET_GROUP_ID:
        return
    lines = ["<b>Paper option exit order status update</b>"]
    for event in events:
        lines.append(
            f"exit batch <code>{event['exit_order_batch_id']}</code> "
            f"leg <code>{event['leg_index']}</code> <code>{event['broker_code']}</code>: "
            f"<code>{event['old_status']}</code> -> <code>{event['new_status']}</code> "
            f"filled <code>{event['dealt_qty'] or 0}</code> @ <code>{event['dealt_avg_price'] or 0}</code>"
        )
    requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": config.TARGET_GROUP_ID,
            "text": "\n".join(lines),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=10,
    )


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


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
