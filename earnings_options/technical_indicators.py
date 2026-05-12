"""Local technical summaries from downloaded equity OHLCV Parquet files."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

DATA_DIR = Path(__file__).resolve().parent.parent / "qc" / "data"


def build_technical_summary(
    *,
    ticker: str,
    report_date: date,
    windows: dict[str, date],
    data_dir: Path = DATA_DIR,
) -> dict[str, Any]:
    ticker_upper = ticker.upper()
    ticker_lower = ticker.lower()
    daily_path = data_dir / "equity" / "usa" / "daily" / f"{ticker_lower}.parquet"
    minute_dir = data_dir / "equity" / "usa" / "minute" / ticker_lower

    daily = _read_equity_parquet(daily_path)
    if daily.empty:
        raise ValueError(f"No daily equity rows found at {daily_path}")
    daily = daily[daily["date"] <= windows["daily_end"]].copy()
    if daily.empty:
        raise ValueError(f"No daily equity rows on or before {windows['daily_end']}")

    daily_indicators = _daily_indicators(daily)
    daily_latest = daily_indicators.iloc[-1]
    minute_summary = _minute_summary(minute_dir)
    as_of_date = daily_latest["date"]

    summary = {
        "ticker": ticker_upper,
        "window_id": f"earnings_{report_date.strftime('%Y%m%d')}",
        "report_date": report_date.isoformat(),
        "as_of_date": as_of_date.isoformat(),
        "daily_window": {
            "start": windows["daily_start"].isoformat(),
            "end": windows["daily_end"].isoformat(),
            "actual_start": daily["date"].iloc[0].isoformat(),
            "actual_end": as_of_date.isoformat(),
            "row_count": int(len(daily)),
        },
        "minute_window": {
            "start": windows["minute_start"].isoformat(),
            "end": windows["minute_end"].isoformat(),
            "actual_start": minute_summary.get("actual_start"),
            "actual_end": minute_summary.get("actual_end"),
            "day_count": minute_summary.get("day_count", 0),
            "row_count": minute_summary.get("row_count", 0),
        },
        "daily": _latest_daily_payload(daily_latest),
        "minute": minute_summary,
    }
    summary["regimes"] = _regimes(summary)
    summary["technical_notes"] = _technical_notes(summary)
    return summary


def _read_equity_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pq.read_table(path).to_pandas()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["time"]).dt.tz_convert("America/New_York").dt.date
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col] / 10000.0
    df["volume"] = df["volume"].astype(float)
    return df.sort_values("date").reset_index(drop=True)


def _daily_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close = out["close"]
    high = out["high"]
    low = out["low"]
    volume = out["volume"]
    prev_close = close.shift(1)
    returns = close.pct_change()
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)

    for window in (20, 50, 100, 200):
        out[f"sma_{window}"] = close.rolling(window).mean()
    out["ema_8"] = close.ewm(span=8, adjust=False).mean()
    out["ema_21"] = close.ewm(span=21, adjust=False).mean()
    out["rsi_14"] = _rsi_wilder(close, 14)
    out["atr_14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    out["atr_14_pct"] = out["atr_14"] / close * 100
    out["hv_20"] = returns.rolling(20).std(ddof=0) * (252 ** 0.5) * 100
    out["hv_60"] = returns.rolling(60).std(ddof=0) * (252 ** 0.5) * 100
    out["return_5d_pct"] = close.pct_change(5) * 100
    out["return_10d_pct"] = close.pct_change(10) * 100
    out["return_20d_pct"] = close.pct_change(20) * 100
    out["return_60d_pct"] = close.pct_change(60) * 100
    out["return_120d_pct"] = close.pct_change(120) * 100
    out["volume_sma_20"] = volume.rolling(20).mean()
    out["volume_vs_20d_avg"] = volume / out["volume_sma_20"]
    out["high_52w"] = high.rolling(252, min_periods=60).max()
    out["low_52w"] = low.rolling(252, min_periods=60).min()
    out["distance_to_52w_high_pct"] = (close / out["high_52w"] - 1) * 100
    out["distance_to_52w_low_pct"] = (close / out["low_52w"] - 1) * 100
    out["above_sma_20"] = close > out["sma_20"]
    out["above_sma_50"] = close > out["sma_50"]
    out["above_sma_200"] = close > out["sma_200"]
    return out


def _rsi_wilder(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _minute_summary(minute_dir: Path) -> dict[str, Any]:
    if not minute_dir.exists():
        return {}
    rows = []
    for path in sorted(minute_dir.glob("*.parquet")):
        df = _read_equity_parquet(path)
        if df.empty:
            continue
        day = df["date"].iloc[0]
        rows.append(_minute_day_summary(day, df))
    if not rows:
        return {}

    latest = rows[-1]
    ranges = [row["intraday_range_pct"] for row in rows if row.get("intraday_range_pct") is not None]
    volumes = [row["volume"] for row in rows if row.get("volume") is not None]
    return {
        "actual_start": rows[0]["date"],
        "actual_end": rows[-1]["date"],
        "day_count": len(rows),
        "row_count": int(sum(row["row_count"] for row in rows)),
        "latest_day": latest,
        "avg_intraday_range_pct": _mean(ranges),
        "avg_daily_minute_volume": _mean(volumes),
    }


def _minute_day_summary(day: date, df: pd.DataFrame) -> dict[str, Any]:
    df = df.sort_values("time").reset_index(drop=True)
    typical = (df["high"] + df["low"] + df["close"]) / 3
    cumulative_volume = df["volume"].cumsum()
    vwap_series = (typical * df["volume"]).cumsum() / cumulative_volume.replace(0, pd.NA)
    vwap = float(vwap_series.iloc[-1])
    open_ = float(df["open"].iloc[0])
    close = float(df["close"].iloc[-1])
    high = float(df["high"].max())
    low = float(df["low"].min())
    first_30_close = float(df["close"].iloc[min(29, len(df) - 1)])
    last_30_open = float(df["open"].iloc[-min(30, len(df))])
    return {
        "date": day.isoformat(),
        "row_count": int(len(df)),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": int(df["volume"].sum()),
        "vwap": vwap,
        "close_vs_vwap_pct": _pct(close, vwap),
        "first_30min_return_pct": _pct(first_30_close, open_),
        "last_30min_return_pct": _pct(close, last_30_open),
        "intraday_range_pct": _pct(high, low),
    }


def _latest_daily_payload(row: pd.Series) -> dict[str, Any]:
    keys = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "sma_20",
        "sma_50",
        "sma_100",
        "sma_200",
        "ema_8",
        "ema_21",
        "rsi_14",
        "atr_14",
        "atr_14_pct",
        "hv_20",
        "hv_60",
        "return_5d_pct",
        "return_10d_pct",
        "return_20d_pct",
        "return_60d_pct",
        "return_120d_pct",
        "volume_vs_20d_avg",
        "high_52w",
        "low_52w",
        "distance_to_52w_high_pct",
        "distance_to_52w_low_pct",
        "above_sma_20",
        "above_sma_50",
        "above_sma_200",
    ]
    payload = {}
    for key in keys:
        value = row.get(key)
        payload[key] = _clean(value)
    return payload


def _regimes(summary: dict[str, Any]) -> dict[str, str]:
    daily = summary["daily"]
    trend_score = sum(bool(daily.get(key)) for key in ("above_sma_20", "above_sma_50", "above_sma_200"))
    if trend_score == 3 and _num(daily.get("sma_20")) > _num(daily.get("sma_50")) > _num(daily.get("sma_200")):
        trend = "bullish"
    elif trend_score == 0 and _num(daily.get("sma_20")) < _num(daily.get("sma_50")) < _num(daily.get("sma_200")):
        trend = "bearish"
    else:
        trend = "mixed"

    rsi = _num(daily.get("rsi_14"))
    ret20 = _num(daily.get("return_20d_pct"))
    if rsi >= 60 and ret20 > 0:
        momentum = "positive"
    elif rsi <= 40 and ret20 < 0:
        momentum = "negative"
    else:
        momentum = "neutral"

    hv20 = _num(daily.get("hv_20"))
    hv60 = _num(daily.get("hv_60"))
    if hv20 > hv60 * 1.25:
        volatility = "expanding"
    elif hv20 < hv60 * 0.75:
        volatility = "contracting"
    else:
        volatility = "normal"

    volume_multiple = _num(daily.get("volume_vs_20d_avg"))
    if volume_multiple >= 1.5:
        volume = "elevated"
    elif volume_multiple <= 0.7:
        volume = "light"
    else:
        volume = "normal"

    return {
        "trend_regime": trend,
        "momentum_regime": momentum,
        "volatility_regime": volatility,
        "volume_regime": volume,
    }


def _technical_notes(summary: dict[str, Any]) -> list[str]:
    daily = summary["daily"]
    regimes = summary["regimes"]
    notes = [
        f"Trend regime: {regimes['trend_regime']}.",
        f"Momentum regime: {regimes['momentum_regime']} with RSI14={daily.get('rsi_14')}.",
        f"20d return={daily.get('return_20d_pct')}%, 60d return={daily.get('return_60d_pct')}%.",
        f"Distance to 52w high={daily.get('distance_to_52w_high_pct')}%, distance to 52w low={daily.get('distance_to_52w_low_pct')}%.",
    ]
    latest_minute = summary.get("minute", {}).get("latest_day")
    if latest_minute:
        notes.append(
            f"Latest intraday close vs VWAP={latest_minute.get('close_vs_vwap_pct')}%, "
            f"range={latest_minute.get('intraday_range_pct')}%."
        )
    return notes


def _pct(numerator: float, denominator: float) -> float | None:
    if denominator in (0, None):
        return None
    return round((numerator / denominator - 1) * 100, 6)


def _mean(values: list[float]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 6)


def _num(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _clean(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        return bool(value)
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return round(value, 6)
    return value
