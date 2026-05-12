"""Resolve paper option order drafts to Moomoo contracts and quote snapshots."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import math
from typing import Any

from broker.moomoo import MoomooClient
from utils.db import PaperOptionOrderDraft, PaperOptionQuoteSnapshot, SessionLocal


def refresh_order_draft_quotes(
    *,
    strategy_run_id: int | None = None,
    ticker: str | None = None,
    draft_id: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Resolve draft broker codes and store quote snapshots.

    This function only uses Moomoo quote APIs. It does not place orders.
    """
    db = SessionLocal()
    moomoo = MoomooClient()
    try:
        drafts = _query_drafts(db, strategy_run_id=strategy_run_id, ticker=ticker, draft_id=draft_id, limit=limit)
        resolved = 0
        quoted = 0
        needs_review = 0
        errors = []
        resolve_cache = _existing_broker_code_cache(db)
        for draft in drafts:
            try:
                if not draft.broker_code:
                    cache_key = (
                        draft.ticker,
                        draft.expiry.isoformat(),
                        str(draft.strike),
                        draft.option_type,
                    )
                    if cache_key not in resolve_cache:
                        contract = moomoo.resolve_us_option_contract(
                            draft.ticker,
                            draft.expiry.isoformat(),
                            float(draft.strike),
                            draft.option_type,
                        )
                        resolve_cache[cache_key] = contract.get("code") if contract else None
                    broker_code = resolve_cache[cache_key]
                    if broker_code:
                        draft.broker_code = broker_code
                        draft.validation_status = "broker_mapped"
                        draft.validation_messages = _messages(draft) + ["resolved_moomoo_contract"]
                        resolved += 1
                    else:
                        draft.validation_status = "needs_review"
                        draft.validation_messages = _messages(draft) + ["moomoo_contract_not_found"]
                        needs_review += 1
                        continue

                snapshot = _snapshot_for_code(moomoo, draft.broker_code)
                if snapshot is None:
                    draft.validation_status = "needs_review"
                    draft.validation_messages = _messages(draft) + ["moomoo_snapshot_not_found"]
                    needs_review += 1
                    continue
                db.add(_quote_snapshot_from_row(draft, snapshot))
                quoted += 1
            except Exception as exc:
                draft.validation_status = "needs_review"
                draft.validation_messages = _messages(draft) + [f"refresh_error: {exc}"]
                errors.append({"draft_id": draft.id, "error": str(exc)})
                needs_review += 1
        db.commit()
        return {
            "draft_count": len(drafts),
            "resolved": resolved,
            "quoted": quoted,
            "needs_review": needs_review,
            "errors": errors,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        moomoo.close()
        db.close()


def _query_drafts(db, *, strategy_run_id, ticker, draft_id, limit) -> list[PaperOptionOrderDraft]:
    query = db.query(PaperOptionOrderDraft)
    if draft_id:
        query = query.filter(PaperOptionOrderDraft.id == draft_id)
    if strategy_run_id:
        query = query.filter(PaperOptionOrderDraft.strategy_run_id == strategy_run_id)
    if ticker:
        query = query.filter(PaperOptionOrderDraft.ticker == ticker.upper())
    query = query.order_by(
        PaperOptionOrderDraft.strategy_run_id.desc(),
        PaperOptionOrderDraft.strategy_index.asc(),
        PaperOptionOrderDraft.leg_index.asc(),
    )
    if limit:
        query = query.limit(limit)
    return query.all()


def _existing_broker_code_cache(db) -> dict[tuple[str, str, str, str], str | None]:
    cache = {}
    rows = (
        db.query(PaperOptionOrderDraft)
        .filter(PaperOptionOrderDraft.broker_code.isnot(None))
        .all()
    )
    for row in rows:
        cache[(row.ticker, row.expiry.isoformat(), str(row.strike), row.option_type)] = row.broker_code
    return cache


def _snapshot_for_code(moomoo: MoomooClient, code: str) -> dict[str, Any] | None:
    data = moomoo.market_snapshot([code])
    if data.empty:
        return None
    rows = data[data["code"].astype(str) == code]
    if rows.empty:
        rows = data
    return rows.iloc[0].to_dict()


def _quote_snapshot_from_row(draft: PaperOptionOrderDraft, row: dict[str, Any]) -> PaperOptionQuoteSnapshot:
    bid = _decimal(row.get("bid_price"))
    ask = _decimal(row.get("ask_price"))
    mid = None
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / Decimal("2")
    return PaperOptionQuoteSnapshot(
        order_draft_id=draft.id,
        strategy_run_id=draft.strategy_run_id,
        ticker=draft.ticker,
        occ_symbol=draft.occ_symbol,
        broker_code=draft.broker_code,
        quote_time=_parse_datetime(row.get("update_time")),
        last_price=_decimal(row.get("last_price")),
        bid_price=bid,
        ask_price=ask,
        mid_price=mid,
        bid_vol=_decimal(row.get("bid_vol")),
        ask_vol=_decimal(row.get("ask_vol")),
        volume=_decimal(row.get("volume")),
        open_interest=_decimal(row.get("option_open_interest")),
        implied_volatility=_decimal(row.get("option_implied_volatility")),
        delta=_decimal(row.get("option_delta")),
        gamma=_decimal(row.get("option_gamma")),
        theta=_decimal(row.get("option_theta")),
        vega=_decimal(row.get("option_vega")),
        rho=_decimal(row.get("option_rho")),
        status="ok",
        raw_snapshot=_jsonable(row),
    )


def _messages(draft: PaperOptionOrderDraft) -> list[str]:
    return list(draft.validation_messages or [])


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_datetime(value: Any):
    if not value:
        return None
    text = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            pass
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
