"""Persist LLM option strategies as paper-trading order drafts."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from broker.moomoo import MoomooClient
from utils.db import EarningsStrategyRun, PaperOptionOrderDraft, SessionLocal

VALID_ACTIONS = {"BUY", "SELL"}
VALID_OPTION_TYPES = {"CALL", "PUT"}


def create_order_drafts_from_files(
    *,
    strategy_json_path: str | Path,
    input_json_path: str | Path | None = None,
    provider: str | None = None,
    account: str | None = None,
    model: str | None = None,
    resolve_moomoo: bool = False,
) -> dict[str, Any]:
    strategy_json = _read_json(strategy_json_path)
    input_json = _read_json(input_json_path) if input_json_path else None
    return create_order_drafts(
        strategy_json=strategy_json,
        input_json=input_json,
        provider=provider,
        account=account,
        model=model,
        resolve_moomoo=resolve_moomoo,
    )


def create_order_drafts(
    *,
    strategy_json: dict[str, Any],
    input_json: dict[str, Any] | None = None,
    provider: str | None = None,
    account: str | None = None,
    model: str | None = None,
    resolve_moomoo: bool = False,
) -> dict[str, Any]:
    ticker = _ticker(strategy_json, input_json)
    report_date = _report_date(strategy_json, input_json)
    metadata = strategy_json.get("metadata") or {}
    provider = provider or metadata.get("provider") or "unknown"
    account = account or metadata.get("account")
    model = model or metadata.get("model")
    warnings = strategy_json.get("data_quality_warnings") or []

    db = SessionLocal()
    moomoo = MoomooClient() if resolve_moomoo else None
    try:
        run = EarningsStrategyRun(
            ticker=ticker,
            report_date=report_date,
            provider=provider,
            model=model,
            account=account,
            status="drafted",
            input_json=input_json,
            strategy_json=strategy_json,
            warnings_json=warnings,
        )
        db.add(run)
        db.flush()

        drafts = []
        for strategy_index, strategy in enumerate(strategy_json.get("strategies") or [], start=1):
            drafts.extend(
                _drafts_for_strategy(
                    run_id=run.id,
                    ticker=ticker,
                    report_date=report_date,
                    strategy_index=strategy_index,
                    strategy=strategy,
                    moomoo=moomoo,
                )
            )
        for draft in drafts:
            db.add(draft)
        db.commit()
        return {
            "strategy_run_id": run.id,
            "ticker": ticker,
            "report_date": report_date.isoformat(),
            "draft_count": len(drafts),
            "strategy_count": len(strategy_json.get("strategies") or []),
            "statuses": _status_counts(drafts),
            "resolve_moomoo": resolve_moomoo,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        if moomoo is not None:
            moomoo.close()
        db.close()


def _drafts_for_strategy(
    *,
    run_id: int,
    ticker: str,
    report_date: date,
    strategy_index: int,
    strategy: dict[str, Any],
    moomoo: MoomooClient | None,
) -> list[PaperOptionOrderDraft]:
    drafts = []
    legs = strategy.get("legs") or []
    for leg_index, leg in enumerate(legs, start=1):
        messages = _validate_leg(leg)
        action = str(leg.get("action") or "").upper()
        option_type = str(leg.get("option_type") or "").upper()
        expiry = _parse_day(leg.get("expiry"))
        strike = _decimal(leg.get("strike"))
        quantity = _int(leg.get("quantity"))
        occ_symbol = _occ_symbol(ticker, expiry, option_type, strike) if expiry and strike is not None else ""
        moomoo_candidate = f"US.{occ_symbol}" if occ_symbol else None
        broker_code = None

        if moomoo is not None and not messages:
            try:
                contract = moomoo.resolve_us_option_contract(ticker, expiry.isoformat(), float(strike), option_type)
                if contract:
                    broker_code = contract.get("code")
                    messages.append("resolved_moomoo_contract")
                else:
                    messages.append("moomoo_contract_not_found")
            except Exception as exc:
                messages.append(f"moomoo_resolve_error: {exc}")

        status = "ready_for_broker_mapping" if not messages else "needs_review"
        if broker_code:
            status = "broker_mapped"

        drafts.append(
            PaperOptionOrderDraft(
                strategy_run_id=run_id,
                ticker=ticker,
                report_date=report_date,
                strategy_index=strategy_index,
                strategy_name=strategy.get("name"),
                scenario=strategy.get("scenario"),
                leg_index=leg_index,
                action=action or "UNKNOWN",
                option_type=option_type or "UNKNOWN",
                expiry=expiry or report_date,
                strike=strike or Decimal("0"),
                quantity=quantity or 0,
                limit_price_hint=_decimal(leg.get("limit_price_hint")),
                estimated_entry_price=_decimal(strategy.get("estimated_entry_price")),
                max_budget_to_use=_decimal(strategy.get("max_budget_to_use")),
                occ_symbol=occ_symbol or "UNKNOWN",
                moomoo_code_candidate=moomoo_candidate,
                broker_code=broker_code,
                validation_status=status,
                validation_messages=messages,
                raw_leg=leg,
            )
        )
    return drafts


def _validate_leg(leg: dict[str, Any]) -> list[str]:
    messages = []
    action = str(leg.get("action") or "").upper()
    option_type = str(leg.get("option_type") or "").upper()
    expiry = _parse_day(leg.get("expiry"))
    strike = _decimal(leg.get("strike"))
    quantity = _int(leg.get("quantity"))
    price = _decimal(leg.get("limit_price_hint"))

    if action not in VALID_ACTIONS:
        messages.append("invalid_action")
    if option_type not in VALID_OPTION_TYPES:
        messages.append("invalid_option_type")
    if expiry is None:
        messages.append("invalid_expiry")
    if strike is None or strike <= 0:
        messages.append("invalid_strike")
    if quantity is None or quantity <= 0:
        messages.append("invalid_quantity")
    if price is None or price <= 0:
        messages.append("invalid_limit_price_hint")
    return messages


def _ticker(strategy_json: dict[str, Any], input_json: dict[str, Any] | None) -> str:
    ticker = strategy_json.get("ticker") or (input_json or {}).get("ticker")
    if not ticker:
        raise ValueError("ticker missing from strategy/input JSON")
    return str(ticker).upper()


def _report_date(strategy_json: dict[str, Any], input_json: dict[str, Any] | None) -> date:
    value = strategy_json.get("earnings_date") or (input_json or {}).get("earnings_date")
    if not value:
        event = (input_json or {}).get("earnings_event") or {}
        value = event.get("report_date")
    if not value:
        raise ValueError("report_date/earnings_date missing from strategy/input JSON")
    return _parse_day(value)


def _occ_symbol(ticker: str, expiry: date, option_type: str, strike: Decimal) -> str:
    strike_int = int((strike * Decimal("1000")).to_integral_value())
    cp = "C" if option_type == "CALL" else "P"
    return f"{ticker.upper()}{expiry.strftime('%y%m%d')}{cp}{strike_int:08d}"


def _read_json(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


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
    if value in (None, ""):
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


def _status_counts(drafts: list[PaperOptionOrderDraft]) -> dict[str, int]:
    counts = {}
    for draft in drafts:
        counts[draft.validation_status] = counts.get(draft.validation_status, 0) + 1
    return counts
