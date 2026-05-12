"""Manual approval and staging for paper option exit plans."""

from __future__ import annotations

import html
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from sqlalchemy import func

from utils.config import config
from utils.db import (
    PaperOptionExitApproval,
    PaperOptionExitOrderBatch,
    PaperOptionExitOrderBatchLeg,
    PaperOptionExitPlan,
    SessionLocal,
)


class ExitWorkflowError(RuntimeError):
    pass


def send_exit_confirmations(*, order_batch_id: int | None = None) -> dict[str, Any]:
    if not config.TELEGRAM_BOT_TOKEN:
        raise ExitWorkflowError("TELEGRAM_BOT_TOKEN is not configured")
    if not config.TARGET_GROUP_ID:
        raise ExitWorkflowError("TARGET_GROUP_ID is not configured")

    db = SessionLocal()
    try:
        plans = _latest_actionable_exit_plans(db, order_batch_id)
        sent = []
        for plan in plans:
            existing = (
                db.query(PaperOptionExitApproval)
                .filter(PaperOptionExitApproval.exit_plan_id == plan.id)
                .first()
            )
            if existing is not None:
                continue
            approval = PaperOptionExitApproval(
                exit_plan_id=plan.id,
                order_batch_id=plan.order_batch_id,
                strategy_run_id=plan.strategy_run_id,
                ticker=plan.ticker,
                action=plan.action,
                status="pending",
                telegram_chat_id=str(config.TARGET_GROUP_ID),
                requested_payload=_approval_payload(plan),
            )
            db.add(approval)
            db.flush()
            response = _send_telegram_message(approval, plan)
            approval.telegram_message_id = str(response.get("message_id", ""))
            sent.append({"exit_approval_id": approval.id, "exit_plan_id": plan.id})
        db.commit()
        return {"sent_count": len(sent), "sent": sent}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def record_exit_decision(*, exit_approval_id: int, decision: str, actor: str | None = None) -> dict[str, Any]:
    decision = decision.lower()
    if decision not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected")
    db = SessionLocal()
    try:
        approval = db.query(PaperOptionExitApproval).filter(PaperOptionExitApproval.id == exit_approval_id).first()
        if approval is None:
            raise ValueError(f"exit approval {exit_approval_id} not found")
        if approval.status != "pending":
            return {"exit_approval_id": approval.id, "status": approval.status, "changed": False}
        approval.status = decision
        approval.decided_at = func.now()
        approval.decision_payload = {"actor": actor, "decision": decision}
        db.commit()
        return {"exit_approval_id": approval.id, "status": approval.status, "changed": True}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def stage_exit_order_batch(*, exit_approval_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        approval = db.query(PaperOptionExitApproval).filter(PaperOptionExitApproval.id == exit_approval_id).first()
        if approval is None:
            raise ExitWorkflowError(f"exit approval {exit_approval_id} not found")
        if approval.status != "approved":
            raise ExitWorkflowError(f"exit approval {exit_approval_id} status is {approval.status}, not approved")
        existing = (
            db.query(PaperOptionExitOrderBatch)
            .filter(PaperOptionExitOrderBatch.exit_approval_id == approval.id)
            .first()
        )
        if existing is not None:
            return {"exit_order_batch_id": existing.id, "created": False, "status": existing.status}
        plan = db.query(PaperOptionExitPlan).filter(PaperOptionExitPlan.id == approval.exit_plan_id).first()
        if plan is None:
            raise ExitWorkflowError(f"exit plan {approval.exit_plan_id} not found")
        legs = plan.exit_legs_json or []
        _validate_exit_legs(legs)
        batch = PaperOptionExitOrderBatch(
            exit_approval_id=approval.id,
            exit_plan_id=plan.id,
            source_order_batch_id=plan.order_batch_id,
            strategy_run_id=plan.strategy_run_id,
            ticker=plan.ticker,
            status="staged",
            payload_json={"action": plan.action, "reasons": plan.reason_json},
        )
        db.add(batch)
        db.flush()
        for index, leg in enumerate(legs, start=1):
            db.add(_exit_batch_leg(batch.id, index, leg))
        db.commit()
        return {
            "exit_order_batch_id": batch.id,
            "created": True,
            "status": batch.status,
            "leg_count": len(legs),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _latest_actionable_exit_plans(db, order_batch_id: int | None) -> list[PaperOptionExitPlan]:
    query = db.query(PaperOptionExitPlan).filter(PaperOptionExitPlan.status.in_(("exit_recommended", "review")))
    if order_batch_id:
        query = query.filter(PaperOptionExitPlan.order_batch_id == order_batch_id)
    rows = query.order_by(PaperOptionExitPlan.order_batch_id.asc(), PaperOptionExitPlan.id.desc()).all()
    latest = {}
    for row in rows:
        latest.setdefault(row.order_batch_id, row)
    return list(latest.values())


def _send_telegram_message(approval: PaperOptionExitApproval, plan: PaperOptionExitPlan) -> dict[str, Any]:
    response = requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": config.TARGET_GROUP_ID,
            "text": _format_exit_confirmation(approval, plan),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "确认退出", "callback_data": f"eo_exit_approve_{approval.id}"},
                    {"text": "拒绝退出", "callback_data": f"eo_exit_reject_{approval.id}"},
                ]]
            },
        },
        timeout=15,
    )
    if response.status_code >= 400:
        raise ExitWorkflowError(f"Telegram send failed: {response.status_code} {response.text}")
    data = response.json()
    if not data.get("ok"):
        raise ExitWorkflowError(f"Telegram send failed: {data}")
    return data["result"]


def _format_exit_confirmation(approval: PaperOptionExitApproval, plan: PaperOptionExitPlan) -> str:
    lines = [
        "<b>期权退出人工确认</b>",
        f"Exit approval ID: <code>{approval.id}</code>",
        f"Ticker: <b>{html.escape(plan.ticker)}</b>",
        f"Action: <code>{html.escape(plan.action)}</code>",
        "",
        "<b>退出订单腿</b>",
    ]
    for leg in plan.exit_legs_json or []:
        lines.append(
            f"<code>{html.escape(str(leg.get('action')))}</code> "
            f"<code>{html.escape(str(leg.get('quantity')))}</code> "
            f"<code>{html.escape(str(leg.get('broker_code')))}</code> "
            f"limit <code>{html.escape(str(leg.get('suggested_limit_price')))}</code>"
        )
    if plan.reason_json:
        lines.extend(["", "<b>原因</b>"])
        lines.extend(f"- {html.escape(str(reason))}" for reason in plan.reason_json)
    lines.extend(["", "点击确认只记录退出批准并允许生成 staged exit batch，不会自动平仓。"])
    return "\n".join(lines)


def _approval_payload(plan: PaperOptionExitPlan) -> dict[str, Any]:
    return {
        "exit_plan_id": plan.id,
        "order_batch_id": plan.order_batch_id,
        "action": plan.action,
        "status": plan.status,
        "reasons": plan.reason_json,
        "exit_legs": plan.exit_legs_json,
    }


def _validate_exit_legs(legs: list[dict[str, Any]]) -> None:
    if not legs:
        raise ExitWorkflowError("exit plan has no legs")
    for leg in legs:
        if int(leg.get("quantity") or 0) <= 0:
            raise ExitWorkflowError("exit leg quantity must be positive")
        if not leg.get("broker_code"):
            raise ExitWorkflowError("exit leg broker_code missing")
        if _decimal(leg.get("suggested_limit_price")) is None:
            raise ExitWorkflowError("exit leg suggested_limit_price missing")


def _exit_batch_leg(batch_id: int, index: int, leg: dict[str, Any]) -> PaperOptionExitOrderBatchLeg:
    return PaperOptionExitOrderBatchLeg(
        exit_order_batch_id=batch_id,
        source_batch_leg_id=int(leg.get("batch_leg_id")),
        leg_index=index,
        action=str(leg.get("action")).upper(),
        quantity=int(leg.get("quantity")),
        broker_code=str(leg.get("broker_code")),
        suggested_limit_price=_decimal(leg.get("suggested_limit_price")),
        order_type="limit",
        status="staged",
        payload_json=leg,
    )


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
