"""Monitor Moomoo paper option order batches."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
from typing import Any

import requests
from sqlalchemy import func

from broker.moomoo_paper import MoomooPaperTrader
from utils.config import config
from utils.db import PaperOptionOrderBatch, PaperOptionOrderBatchLeg, SessionLocal

TERMINAL_LEG_STATUSES = {"filled", "cancelled", "failed", "disabled", "deleted"}


def refresh_paper_order_batches(
    *,
    order_batch_id: int | None = None,
    notify: bool = False,
) -> dict[str, Any]:
    """Refresh submitted paper order status from Moomoo and update local DB."""
    db = SessionLocal()
    trader = MoomooPaperTrader()
    try:
        batches = _query_batches(db, order_batch_id)
        refreshed = []
        changed_events = []
        for batch in batches:
            legs = (
                db.query(PaperOptionOrderBatchLeg)
                .filter(PaperOptionOrderBatchLeg.order_batch_id == batch.id)
                .order_by(PaperOptionOrderBatchLeg.leg_index.asc())
                .all()
            )
            for leg in legs:
                if not leg.broker_order_id:
                    continue
                old_status = leg.status
                order_row = _order_row(trader, leg.broker_order_id)
                if order_row is None:
                    continue
                _apply_order_row(leg, order_row)
                if leg.status != old_status:
                    changed_events.append(_event_payload(batch, leg, old_status))
            batch.status = _batch_status(legs)
            refreshed.append({"order_batch_id": batch.id, "status": batch.status})

        db.commit()
        if notify and changed_events:
            _send_telegram_notification(changed_events)
        return {
            "batch_count": len(refreshed),
            "refreshed": refreshed,
            "changed_count": len(changed_events),
            "changed_events": changed_events,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        trader.close()
        db.close()


def _query_batches(db, order_batch_id: int | None) -> list[PaperOptionOrderBatch]:
    query = db.query(PaperOptionOrderBatch)
    if order_batch_id:
        query = query.filter(PaperOptionOrderBatch.id == order_batch_id)
    else:
        query = query.filter(PaperOptionOrderBatch.status.in_(("submitted", "partial_filled", "partial_failed")))
    return query.order_by(PaperOptionOrderBatch.id.asc()).all()


def _order_row(trader: MoomooPaperTrader, order_id: str) -> dict[str, Any] | None:
    data = trader.orders(order_id)
    if data is None or data.empty:
        return None
    return data.iloc[0].to_dict()


def _apply_order_row(leg: PaperOptionOrderBatchLeg, row: dict[str, Any]) -> None:
    broker_status = str(row.get("order_status") or "").upper()
    leg.status = _normalize_order_status(broker_status)
    leg.dealt_qty = _decimal(row.get("dealt_qty"))
    leg.dealt_avg_price = _decimal(row.get("dealt_avg_price"))
    leg.last_err_msg = str(row.get("last_err_msg") or "") or None
    leg.last_status_at = func.now()
    payload = dict(leg.payload_json or {})
    payload["latest_broker_order"] = _jsonable(row)
    leg.payload_json = payload


def _normalize_order_status(status: str) -> str:
    status = status.upper()
    if status in {"FILLED_ALL"}:
        return "filled"
    if status in {"FILLED_PART"}:
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


def _batch_status(legs: list[PaperOptionOrderBatchLeg]) -> str:
    statuses = {leg.status for leg in legs}
    if statuses == {"filled"}:
        return "filled"
    if any(status in {"failed", "disabled", "deleted"} for status in statuses):
        return "attention_required"
    if any(status == "cancelled" for status in statuses):
        return "cancelled" if statuses == {"cancelled"} else "attention_required"
    if any(status == "partial_filled" for status in statuses):
        return "partial_filled"
    if any(status == "filled" for status in statuses):
        return "partial_filled"
    if statuses == {"submitted"}:
        return "submitted"
    return "attention_required"


def _event_payload(batch: PaperOptionOrderBatch, leg: PaperOptionOrderBatchLeg, old_status: str) -> dict[str, Any]:
    return {
        "order_batch_id": batch.id,
        "ticker": batch.ticker,
        "strategy_name": batch.strategy_name,
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
    lines = ["<b>Paper option order status update</b>"]
    for event in events:
        lines.append(
            f"batch <code>{event['order_batch_id']}</code> leg <code>{event['leg_index']}</code> "
            f"<code>{event['broker_code']}</code>: "
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
