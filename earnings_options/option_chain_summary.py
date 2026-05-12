"""Local option-chain summaries from downloaded option Parquet files."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

DATA_DIR = Path(__file__).resolve().parent.parent / "qc" / "data"
OCC_RE = re.compile(r"^(?P<ticker>[A-Z]+)(?P<expiry>\d{6})(?P<right>[CP])(?P<strike>\d{8})$")


def build_option_chain_summary(
    *,
    ticker: str,
    report_date: date,
    spot_price: float,
    option_paths: list[Path],
) -> dict[str, Any]:
    ticker = ticker.upper()
    frames = []
    for path in sorted(option_paths):
        frame = _read_option_day(path)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        raise ValueError(f"No option rows available for {ticker}")

    df = pd.concat(frames, ignore_index=True)
    df = _with_symbol_parts(df)
    df = df.dropna(subset=["expiry", "strike", "right"]).copy()
    if df.empty:
        raise ValueError(f"No parsable option symbols available for {ticker}")

    day_summaries = []
    for trade_date, day in df.groupby("trade_date"):
        day_summaries.append(_summarize_day(day, ticker, report_date, spot_price, trade_date))
    day_summaries = [item for item in day_summaries if item]
    if not day_summaries:
        raise ValueError(f"No summarizable option days available for {ticker}")

    latest = day_summaries[-1]
    summary = {
        "ticker": ticker,
        "window_id": f"earnings_{report_date.strftime('%Y%m%d')}",
        "report_date": report_date.isoformat(),
        "as_of_date": latest["trade_date"],
        "spot_price": round(spot_price, 6),
        "front_expiry": latest.get("front_expiry"),
        "days_to_expiry": latest.get("days_to_expiry"),
        "atm_strike": latest.get("atm_strike"),
        "atm_call_mid": latest.get("atm_call_mid"),
        "atm_put_mid": latest.get("atm_put_mid"),
        "atm_straddle_mid": latest.get("atm_straddle_mid"),
        "implied_move_pct": latest.get("implied_move_pct"),
        "median_spread_pct": latest.get("median_spread_pct"),
        "atm_spread_pct": latest.get("atm_spread_pct"),
        "total_call_volume": latest.get("total_call_volume"),
        "total_put_volume": latest.get("total_put_volume"),
        "call_put_volume_ratio": latest.get("call_put_volume_ratio"),
        "liquidity_score": _liquidity_score(latest),
        "volatility_pricing_score": _volatility_score(latest),
        "directional_skew_score": _skew_score(latest),
        "top_volume_contracts": latest.get("top_volume_contracts", []),
        "top_premium_contracts": latest.get("top_premium_contracts", []),
        "tradable_candidates": latest.get("tradable_candidates", {}),
        "straddle_trend_by_day": [
            {
                "date": item["trade_date"],
                "atm_straddle_mid": item.get("atm_straddle_mid"),
                "implied_move_pct": item.get("implied_move_pct"),
                "median_spread_pct": item.get("median_spread_pct"),
                "call_put_volume_ratio": item.get("call_put_volume_ratio"),
            }
            for item in day_summaries
        ],
        "day_summaries": day_summaries,
    }
    summary["option_notes"] = _option_notes(summary)
    return summary


def _read_option_day(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pq.read_table(path).to_pandas()
    if df.empty:
        return df
    df["trade_date"] = pd.to_datetime(df["time"]).dt.tz_convert("America/New_York").dt.date
    for col in ["open", "high", "low", "close", "bid_close", "ask_close"]:
        df[col] = df[col] / 10000.0
    return df


def _with_symbol_parts(df: pd.DataFrame) -> pd.DataFrame:
    parsed = df["symbol"].map(parse_occ_symbol)
    parts = pd.DataFrame(parsed.tolist(), index=df.index)
    return pd.concat([df, parts], axis=1)


def parse_occ_symbol(symbol: str) -> dict[str, Any]:
    match = OCC_RE.match(str(symbol))
    if not match:
        return {"expiry": None, "right": None, "strike": None}
    expiry = datetime.strptime(match.group("expiry"), "%y%m%d").date()
    right = "call" if match.group("right") == "C" else "put"
    strike = int(match.group("strike")) / 1000.0
    return {"expiry": expiry, "right": right, "strike": strike}


def _summarize_day(day: pd.DataFrame, ticker: str, report_date: date, spot_price: float, trade_date: date) -> dict[str, Any] | None:
    contract = _contract_last_rows(day)
    if contract.empty:
        return None
    contract["mid"] = (contract["bid_close"] + contract["ask_close"]) / 2
    contract["spread_pct"] = (contract["ask_close"] - contract["bid_close"]) / contract["mid"] * 100
    contract.loc[contract["mid"] <= 0, "spread_pct"] = None
    contract["premium"] = contract["close"].fillna(contract["mid"]).fillna(0) * contract["volume"].fillna(0) * 100
    front_expiry = _front_expiry(contract, trade_date)
    front = contract[contract["expiry"] == front_expiry].copy()
    if front.empty:
        return None
    atm_strike = min(front["strike"].unique(), key=lambda value: abs(value - spot_price))
    atm = front[front["strike"] == atm_strike]
    atm_call = _side_row(atm, "call")
    atm_put = _side_row(atm, "put")
    atm_call_mid = _value(atm_call, "mid")
    atm_put_mid = _value(atm_put, "mid")
    atm_straddle = _sum_or_none(atm_call_mid, atm_put_mid)
    implied_move_pct = _pct(atm_straddle, spot_price) if atm_straddle is not None else None
    atm_spread_pct = _mean([_value(atm_call, "spread_pct"), _value(atm_put, "spread_pct")])
    call_volume = int(contract.loc[contract["right"] == "call", "volume"].fillna(0).sum())
    put_volume = int(contract.loc[contract["right"] == "put", "volume"].fillna(0).sum())
    return {
        "trade_date": trade_date.isoformat(),
        "front_expiry": front_expiry.isoformat(),
        "days_to_expiry": (front_expiry - trade_date).days,
        "spot_price": round(spot_price, 6),
        "atm_strike": round(float(atm_strike), 6),
        "atm_call_mid": _round(atm_call_mid),
        "atm_put_mid": _round(atm_put_mid),
        "atm_straddle_mid": _round(atm_straddle),
        "implied_move_pct": _round(implied_move_pct),
        "median_spread_pct": _round(contract["spread_pct"].dropna().median()),
        "atm_spread_pct": _round(atm_spread_pct),
        "total_call_volume": call_volume,
        "total_put_volume": put_volume,
        "call_put_volume_ratio": _round(call_volume / put_volume) if put_volume else None,
        "contracts": int(contract["symbol"].nunique()),
        "contracts_with_quote": int(contract[contract["mid"].notna()]["symbol"].nunique()),
        "contracts_with_trade": int(contract[contract["volume"].fillna(0) > 0]["symbol"].nunique()),
        "quote_coverage_pct": _round(contract["mid"].notna().mean() * 100),
        "skew_proxy": _skew_proxy(front, spot_price),
        "top_volume_contracts": _top_contracts(contract, "volume"),
        "top_premium_contracts": _top_contracts(contract, "premium"),
        "tradable_candidates": _tradable_candidates(front, spot_price, implied_move_pct),
    }


def _contract_last_rows(day: pd.DataFrame) -> pd.DataFrame:
    latest = day.sort_values("time").groupby("symbol", as_index=False).tail(1).copy()
    volumes = day.groupby("symbol", as_index=False)["volume"].sum(min_count=1).rename(columns={"volume": "day_volume"})
    latest = latest.merge(volumes, on="symbol", how="left")
    latest["volume"] = latest["day_volume"]
    latest = latest.drop(columns=["day_volume"])
    return latest


def _front_expiry(contract: pd.DataFrame, trade_date: date) -> date:
    expiries = sorted(expiry for expiry in contract["expiry"].unique() if expiry >= trade_date)
    return expiries[0] if expiries else sorted(contract["expiry"].unique())[0]


def _side_row(frame: pd.DataFrame, side: str) -> pd.Series | None:
    rows = frame[frame["right"] == side]
    if rows.empty:
        return None
    return rows.iloc[0]


def _skew_proxy(front: pd.DataFrame, spot_price: float) -> dict[str, Any]:
    atm_put = _nearest_option(front, "put", spot_price)
    atm_call = _nearest_option(front, "call", spot_price)
    put_5 = _nearest_option(front, "put", spot_price * 0.95)
    call_5 = _nearest_option(front, "call", spot_price * 1.05)
    put_ratio = _ratio(_value(put_5, "mid"), _value(atm_put, "mid"))
    call_ratio = _ratio(_value(call_5, "mid"), _value(atm_call, "mid"))
    return {
        "otm_5pct_put_mid": _round(_value(put_5, "mid")),
        "otm_5pct_call_mid": _round(_value(call_5, "mid")),
        "otm_5pct_put_to_atm_put": _round(put_ratio),
        "otm_5pct_call_to_atm_call": _round(call_ratio),
        "put_call_skew_proxy": _round(put_ratio - call_ratio) if put_ratio is not None and call_ratio is not None else None,
    }


def _nearest_option(frame: pd.DataFrame, side: str, target_strike: float) -> pd.Series | None:
    rows = frame[frame["right"] == side].copy()
    if rows.empty:
        return None
    rows["distance"] = (rows["strike"] - target_strike).abs()
    return rows.sort_values("distance").iloc[0]


def _top_contracts(contract: pd.DataFrame, metric: str, n: int = 5) -> list[dict[str, Any]]:
    cols = ["symbol", "right", "expiry", "strike", "volume", "mid", "premium", "spread_pct"]
    rows = contract.sort_values(metric, ascending=False).head(n)
    out = []
    for _, row in rows.iterrows():
        out.append({col: _json_value(row[col]) for col in cols})
    return out


def _tradable_candidates(front: pd.DataFrame, spot_price: float, implied_move_pct: float | None) -> dict[str, Any]:
    """Compact candidate list for LLM strike selection.

    The full chain stays in Parquet. This payload gives the model actual listed
    contracts around ATM and the implied-move band without making the prompt huge.
    """
    move = (implied_move_pct or 5.0) / 100.0
    targets = {
        "atm": spot_price,
        "up_half_implied_move": spot_price * (1 + move / 2),
        "up_implied_move": spot_price * (1 + move),
        "down_half_implied_move": spot_price * (1 - move / 2),
        "down_implied_move": spot_price * (1 - move),
    }
    return {
        label: {
            "call": _candidate_payload(_nearest_option(front, "call", target)),
            "put": _candidate_payload(_nearest_option(front, "put", target)),
        }
        for label, target in targets.items()
    }


def _candidate_payload(row: pd.Series | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "symbol": _json_value(row.get("symbol")),
        "right": _json_value(row.get("right")),
        "expiry": _json_value(row.get("expiry")),
        "strike": _json_value(row.get("strike")),
        "bid": _json_value(row.get("bid_close")),
        "ask": _json_value(row.get("ask_close")),
        "mid": _json_value(row.get("mid")),
        "close": _json_value(row.get("close")),
        "volume": _json_value(row.get("volume")),
        "spread_pct": _json_value(row.get("spread_pct")),
    }


def _liquidity_score(summary: dict[str, Any]) -> int:
    score = 0
    if (summary.get("quote_coverage_pct") or 0) >= 80:
        score += 30
    if (summary.get("median_spread_pct") or 999) <= 25:
        score += 30
    if (summary.get("atm_spread_pct") or 999) <= 15:
        score += 20
    if (summary.get("total_call_volume") or 0) + (summary.get("total_put_volume") or 0) > 500:
        score += 20
    return min(score, 100)


def _volatility_score(summary: dict[str, Any]) -> int:
    move = summary.get("implied_move_pct")
    if move is None:
        return 0
    if move >= 12:
        return 90
    if move >= 8:
        return 70
    if move >= 5:
        return 50
    return 30


def _skew_score(summary: dict[str, Any]) -> int:
    skew = (summary.get("skew_proxy") or {}).get("put_call_skew_proxy")
    if skew is None:
        return 0
    if skew > 0.25:
        return -50
    if skew < -0.25:
        return 50
    return 0


def _option_notes(summary: dict[str, Any]) -> list[str]:
    return [
        f"ATM straddle implied move is {summary.get('implied_move_pct')}% using front expiry {summary.get('front_expiry')}.",
        f"Liquidity score is {summary.get('liquidity_score')} with median spread {summary.get('median_spread_pct')}%.",
        f"Call/put volume ratio is {summary.get('call_put_volume_ratio')}.",
        f"Directional skew score is {summary.get('directional_skew_score')} based on 5% OTM moneyness proxy.",
    ]


def _value(row: pd.Series | None, key: str) -> float | None:
    if row is None:
        return None
    value = row.get(key)
    if pd.isna(value):
        return None
    return float(value)


def _sum_or_none(*values: float | None) -> float | None:
    if any(value is None for value in values):
        return None
    return float(sum(values))


def _pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator * 100


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _mean(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None and not pd.isna(value)]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _round(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 6)


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return round(value, 6)
    return value
