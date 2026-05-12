"""Reusable QuantConnect historical earnings anchor downloader."""

from __future__ import annotations

import base64
import csv
import io
import json
import zlib
from datetime import date, datetime
from pathlib import Path

from qc.earnings_calendar import normalize_date
from qc.qc_client import QCClient

ROOT = Path(__file__).parent
PROJECT_DIR = ROOT / "Z05_HistoricalEarningsSmokeTest"
CONFIG_FILE = PROJECT_DIR / "config.json"
MAIN_PY = PROJECT_DIR / "main.py"
OUTPUT_DIR = ROOT / "data" / "historical_earnings"
LAST_BT_FILE = ROOT / ".last_historical_earnings_bt_id"


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def decode_rows(bt_result: dict) -> list[dict]:
    stats = bt_result.get("runtimeStatistics") or {}
    n_chunks = int(stats.get("HISTEARN_N") or 0)
    if n_chunks <= 0:
        raise ValueError(f"No HISTEARN chunks found. Runtime statistic keys: {list(stats)[:30]}")
    encoded = "".join(stats.get(f"HISTEARN_{i:04d}", "") for i in range(n_chunks))
    text = zlib.decompress(base64.b64decode(encoded)).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def write_outputs(rows: list[dict], ticker: str, start: str, end: str) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"historical_earnings_{ticker}_{start}_{end}"
    csv_path = OUTPUT_DIR / f"{stem}.csv"
    json_path = OUTPUT_DIR / f"{stem}.json"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["ticker"])
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return csv_path, json_path


def download_historical_earnings(
    *,
    ticker: str,
    start: str | date,
    end: str | date,
    save_outputs: bool = True,
) -> list[dict]:
    ticker = ticker.upper()
    start_text = normalize_date(start)
    end_text = normalize_date(end)
    config = load_config()
    project_id = int(config["cloud-id"])
    qc = QCClient()
    qc.push_algorithm(project_id, MAIN_PY)
    compile_id = qc.compile(project_id)
    bt_id = qc.create_backtest(
        project_id,
        compile_id,
        f"HistEarn_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        parameters={"ticker": ticker, "start_date": start_text, "end_date": end_text},
    )
    bt_result = qc.wait_for_backtest(project_id, bt_id, required_prefixes=("HISTEARN_",))
    LAST_BT_FILE.write_text(bt_id, encoding="utf-8")
    rows = decode_rows(bt_result)
    if save_outputs:
        write_outputs(rows, ticker, start_text, end_text)
    return rows
