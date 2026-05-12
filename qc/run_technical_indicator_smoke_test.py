#!/usr/bin/env python3
"""Run QC technical indicator smoke test and compare with local Parquet data."""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import sys
import zlib
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qc.earnings_calendar import normalize_date
from qc.qc_client import QCClient

ROOT = Path(__file__).parent
PROJECT_DIR = ROOT / "Z09_TechnicalIndicatorSmokeTest"
CONFIG_FILE = PROJECT_DIR / "config.json"
MAIN_PY = PROJECT_DIR / "main.py"


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def save_config(config: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(config, indent=4) + "\n", encoding="utf-8")


def ensure_project(qc: QCClient) -> int:
    config = load_config()
    project_id = config.get("cloud-id")
    if project_id:
        return int(project_id)
    data = qc.post(
        "projects/create",
        {
            "name": "A02 Technical Indicator Smoke Test",
            "language": "Py",
            "organizationId": config.get("organization-id"),
        },
    )
    project = (data.get("projects") or [])[0]
    project_id = int(project.get("projectId") or project.get("project_id") or project.get("id"))
    config["cloud-id"] = project_id
    save_config(config)
    print(f"  Created QC project id={project_id}")
    return project_id


def decode_tech_rows(bt_result: dict) -> list[dict]:
    stats = bt_result.get("runtimeStatistics") or {}
    n_chunks = int(stats.get("TECH_N") or 0)
    if n_chunks <= 0:
        raise ValueError(f"No TECH chunks found. Runtime statistic keys: {list(stats)[:30]}")
    encoded = "".join(stats.get(f"TECH_{i:04d}", "") for i in range(n_chunks))
    text = zlib.decompress(base64.b64decode(encoded)).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def local_indicators(ticker: str, path: Path) -> pd.DataFrame:
    df = pq.read_table(path).to_pandas()
    df["date"] = pd.to_datetime(df["time"]).dt.date.astype(str)
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col] / 10000.0
    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"]
    high = df["high"]
    low = df["low"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)

    out = pd.DataFrame({"date": df["date"], "ticker": ticker.upper()})
    out["sma20"] = close.rolling(20).mean()
    out["sma50"] = close.rolling(50).mean()
    out["sma200"] = close.rolling(200).mean()
    out["ema8"] = close.ewm(span=8, adjust=False).mean()
    out["ema21"] = close.ewm(span=21, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss
    out["rsi14"] = 100 - (100 / (1 + rs))
    out["atr14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    out["std20"] = close.rolling(20).std(ddof=0)
    out["std60"] = close.rolling(60).std(ddof=0)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", default="ACM")
    parser.add_argument("--start", default="2023-05-12")
    parser.add_argument("--end", default="2026-05-08")
    parser.add_argument("--local-parquet", type=Path, default=Path("qc/data/equity/usa/daily/acm.parquet"))
    args = parser.parse_args()

    start = normalize_date(args.start)
    end = normalize_date(args.end)
    qc = QCClient()
    project_id = ensure_project(qc)
    qc.push_algorithm(project_id, MAIN_PY)
    compile_id = qc.compile(project_id)
    bt_id = qc.create_backtest(
        project_id,
        compile_id,
        f"TechnicalIndicators_{args.ticker.upper()}_{start}_{end}",
        parameters={"ticker": args.ticker.upper(), "start_date": start, "end_date": end},
    )
    bt_result = qc.wait_for_backtest(project_id, bt_id, required_prefixes=("TECH_",))
    qc_rows = decode_tech_rows(bt_result)
    if not qc_rows:
        raise RuntimeError("QC returned no indicator rows")
    qc_last = qc_rows[-1]
    local = local_indicators(args.ticker, args.local_parquet)
    local_last = local[local["date"] == qc_last["date"]].iloc[-1]

    print(f"Compared date: {qc_last['date']}")
    for name in ["sma20", "sma50", "sma200", "ema8", "ema21", "rsi14", "atr14", "std20", "std60"]:
        qc_value = float(qc_last[name]) if qc_last[name] else None
        local_value = float(local_last[name])
        diff = None if qc_value is None else local_value - qc_value
        print(f"{name:7s} qc={qc_value:.6f} local={local_value:.6f} diff={diff:.6f}")


if __name__ == "__main__":
    main()
