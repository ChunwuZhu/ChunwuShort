"""Parquet helpers for QuantConnect bar exports.

Prices are stored as integer USD * 10,000, matching the LEAN export format.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc

BARS_SCHEMA = pa.schema(
    [
        pa.field("time", pa.timestamp("us", tz="UTC")),
        pa.field("symbol", pa.string()),
        pa.field("open", pa.int64()),
        pa.field("high", pa.int64()),
        pa.field("low", pa.int64()),
        pa.field("close", pa.int64()),
        pa.field("volume", pa.int64()),
        pa.field("bid_open", pa.int64()),
        pa.field("bid_high", pa.int64()),
        pa.field("bid_low", pa.int64()),
        pa.field("bid_close", pa.int64()),
        pa.field("bid_size", pa.int64()),
        pa.field("ask_open", pa.int64()),
        pa.field("ask_high", pa.int64()),
        pa.field("ask_low", pa.int64()),
        pa.field("ask_close", pa.int64()),
        pa.field("ask_size", pa.int64()),
    ]
)

EQUITY_BARS_SCHEMA = pa.schema(
    [
        pa.field("time", pa.timestamp("us", tz="UTC")),
        pa.field("symbol", pa.string()),
        pa.field("open", pa.int64()),
        pa.field("high", pa.int64()),
        pa.field("low", pa.int64()),
        pa.field("close", pa.int64()),
        pa.field("volume", pa.int64()),
    ]
)


def ms_to_utc(day: date, ms: int) -> datetime:
    midnight_et = datetime(day.year, day.month, day.day, tzinfo=EASTERN)
    return (midnight_et + timedelta(milliseconds=ms)).astimezone(UTC)


def rows_to_table(rows: list[tuple]) -> pa.Table:
    if not rows:
        return pa.table({f.name: pa.array([], type=f.type) for f in BARS_SCHEMA}, schema=BARS_SCHEMA)
    cols = list(zip(*rows))
    times = pa.array([t.replace(tzinfo=None) for t in cols[0]], type=pa.timestamp("us"))
    times = times.cast(pa.timestamp("us", tz="UTC"))
    symbols = pa.array(cols[1], type=pa.string())
    int_arrays = [pa.array(list(c), type=pa.int64()) for c in cols[2:]]
    arrays = [times, symbols] + int_arrays
    return pa.table(dict(zip([f.name for f in BARS_SCHEMA], arrays)), schema=BARS_SCHEMA)


def write_day_parquet(out_path: Path, rows: list[tuple]) -> None:
    table = rows_to_table(rows).sort_by([("time", "ascending"), ("symbol", "ascending")])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_path, compression="zstd", row_group_size=100_000)


def equity_rows_to_table(rows: list[tuple]) -> pa.Table:
    if not rows:
        return pa.table({f.name: pa.array([], type=f.type) for f in EQUITY_BARS_SCHEMA}, schema=EQUITY_BARS_SCHEMA)
    cols = list(zip(*rows))
    times = pa.array([t.replace(tzinfo=None) for t in cols[0]], type=pa.timestamp("us"))
    times = times.cast(pa.timestamp("us", tz="UTC"))
    symbols = pa.array(cols[1], type=pa.string())
    int_arrays = [pa.array(list(c), type=pa.int64()) for c in cols[2:]]
    arrays = [times, symbols] + int_arrays
    return pa.table(dict(zip([f.name for f in EQUITY_BARS_SCHEMA], arrays)), schema=EQUITY_BARS_SCHEMA)


def write_equity_parquet(out_path: Path, rows: list[tuple]) -> None:
    table = equity_rows_to_table(rows).sort_by([("time", "ascending"), ("symbol", "ascending")])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_path, compression="zstd", row_group_size=100_000)
