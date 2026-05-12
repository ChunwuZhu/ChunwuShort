"""Telegram manual confirmation requests for adjusted paper option plans."""

from __future__ import annotations

import html
from typing import Any

import requests
from sqlalchemy import func

from utils.config import config
from utils.db import PaperOptionAdjustmentSuggestion, PaperOptionManualApproval, SessionLocal


class ManualConfirmationError(RuntimeError):
    pass


def send_manual_confirmations(*, strategy_run_id: int, only_ready: bool = True) -> dict[str, Any]:
    """Send Telegram approval requests for adjustment suggestions.

    This only requests approval. It does not stage or place any broker order.
    """
    if not config.TELEGRAM_BOT_TOKEN:
        raise ManualConfirmationError("TELEGRAM_BOT_TOKEN is not configured")
    if not config.TARGET_GROUP_ID:
        raise ManualConfirmationError("TARGET_GROUP_ID is not configured")

    db = SessionLocal()
    try:
        query = db.query(PaperOptionAdjustmentSuggestion).filter(
            PaperOptionAdjustmentSuggestion.strategy_run_id == strategy_run_id
        )
        if only_ready:
            query = query.filter(PaperOptionAdjustmentSuggestion.status == "ready_after_adjustment")
        suggestions = query.order_by(PaperOptionAdjustmentSuggestion.strategy_index.asc()).all()
        sent = []
        for suggestion in suggestions:
            approval = PaperOptionManualApproval(
                adjustment_suggestion_id=suggestion.id,
                strategy_run_id=suggestion.strategy_run_id,
                ticker=suggestion.ticker,
                report_date=suggestion.report_date,
                strategy_index=suggestion.strategy_index,
                strategy_name=suggestion.strategy_name,
                status="pending",
                telegram_chat_id=str(config.TARGET_GROUP_ID),
                requested_payload=_approval_payload(suggestion),
            )
            db.add(approval)
            db.flush()

            response = _send_telegram_message(approval, suggestion)
            approval.telegram_message_id = str(response.get("message_id", ""))
            sent.append(
                {
                    "approval_id": approval.id,
                    "suggestion_id": suggestion.id,
                    "strategy_index": suggestion.strategy_index,
                    "telegram_message_id": approval.telegram_message_id,
                }
            )
        db.commit()
        return {
            "strategy_run_id": strategy_run_id,
            "sent_count": len(sent),
            "sent": sent,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def record_manual_decision(*, approval_id: int, decision: str, actor: str | None = None) -> dict[str, Any]:
    decision = decision.lower()
    if decision not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected")
    db = SessionLocal()
    try:
        approval = db.query(PaperOptionManualApproval).filter(PaperOptionManualApproval.id == approval_id).first()
        if approval is None:
            raise ValueError(f"manual approval {approval_id} not found")
        if approval.status != "pending":
            return {
                "approval_id": approval.id,
                "status": approval.status,
                "changed": False,
            }
        approval.status = decision
        approval.decided_at = func.now()
        approval.decision_payload = {"actor": actor, "decision": decision}
        db.commit()
        return {
            "approval_id": approval.id,
            "status": approval.status,
            "changed": True,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def format_confirmation_message(approval: PaperOptionManualApproval, suggestion: PaperOptionAdjustmentSuggestion) -> str:
    legs = suggestion.suggested_legs_json or []
    lines = [
        "<b>期权策略人工确认</b>",
        f"Approval ID: <code>{approval.id}</code>",
        f"Ticker: <b>{html.escape(suggestion.ticker)}</b>",
        f"财报日: <code>{suggestion.report_date}</code>",
        f"策略: <b>{html.escape(str(suggestion.strategy_name or ''))}</b>",
        f"建议: <code>{html.escape(suggestion.recommendation)}</code>",
        f"数量: <code>{suggestion.original_quantity} -> {suggestion.suggested_quantity}</code>",
        f"保守成本: <code>{suggestion.original_conservative_debit} -> {suggestion.suggested_conservative_debit}</code>",
        f"预算: <code>{suggestion.budget_limit}</code>",
        "",
        "<b>建议订单腿</b>",
    ]
    for leg in legs:
        lines.append(
            " ".join(
                [
                    f"<code>{html.escape(str(leg.get('action')))}</code>",
                    f"<code>{html.escape(str(leg.get('quantity')))}</code>",
                    f"<code>{html.escape(str(leg.get('broker_code')))}</code>",
                    f"limit <code>{html.escape(str(leg.get('suggested_limit_price')))}</code>",
                ]
            )
        )
    reasons = suggestion.reason_json or []
    if reasons:
        lines.extend(["", "<b>原因</b>"])
        lines.extend(f"- {html.escape(str(reason))}" for reason in reasons)
    lines.extend(["", "点击确认只记录人工批准状态，不会下单。"])
    return "\n".join(lines)


def _send_telegram_message(approval: PaperOptionManualApproval, suggestion: PaperOptionAdjustmentSuggestion) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": config.TARGET_GROUP_ID,
            "text": format_confirmation_message(approval, suggestion),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {"text": "确认", "callback_data": f"eo_approve_{approval.id}"},
                        {"text": "拒绝", "callback_data": f"eo_reject_{approval.id}"},
                    ],
                ]
            },
        },
        timeout=15,
    )
    if response.status_code >= 400:
        raise ManualConfirmationError(f"Telegram send failed: {response.status_code} {response.text}")
    data = response.json()
    if not data.get("ok"):
        raise ManualConfirmationError(f"Telegram send failed: {data}")
    return data["result"]


def _approval_payload(suggestion: PaperOptionAdjustmentSuggestion) -> dict[str, Any]:
    return {
        "suggestion_id": suggestion.id,
        "strategy_run_id": suggestion.strategy_run_id,
        "strategy_index": suggestion.strategy_index,
        "recommendation": suggestion.recommendation,
        "status": suggestion.status,
        "suggested_quantity": suggestion.suggested_quantity,
        "suggested_conservative_debit": str(suggestion.suggested_conservative_debit),
        "suggested_legs": suggestion.suggested_legs_json,
        "reasons": suggestion.reason_json,
    }
