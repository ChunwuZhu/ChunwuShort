"""Reusable QuantConnect fundamental snapshot downloader."""

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
PROJECT_DIR = ROOT / "Z04_FundamentalSmokeTest"
CONFIG_FILE = PROJECT_DIR / "config.json"
MAIN_PY = PROJECT_DIR / "main.py"
OUTPUT_DIR = ROOT / "data" / "fundamentals"
LAST_BT_FILE = ROOT / ".last_fundamentals_bt_id"


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def decode_rows(bt_result: dict) -> list[dict]:
    stats = bt_result.get("runtimeStatistics") or {}
    n_chunks = int(stats.get("FUNDAMENTALS_N") or 0)
    if n_chunks <= 0:
        raise ValueError(f"No FUNDAMENTALS chunks found. Runtime statistic keys: {list(stats)[:30]}")
    encoded = "".join(stats.get(f"FUNDAMENTALS_{i:04d}", "") for i in range(n_chunks))
    text = zlib.decompress(base64.b64decode(encoded)).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def write_outputs(rows: list[dict], run_date: str) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"qc_fundamentals_{run_date}"
    csv_path = OUTPUT_DIR / f"{stem}.csv"
    json_path = OUTPUT_DIR / f"{stem}.json"
    fieldnames = list(rows[0].keys()) if rows else ["ticker"]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return csv_path, json_path


def download_fundamentals(
    *,
    tickers: list[str],
    run_date: str | date,
    max_tickers: int = 500,
    save_outputs: bool = True,
) -> list[dict]:
    cleaned = sorted({ticker.strip().upper() for ticker in tickers if ticker.strip()})
    if not cleaned:
        return []
    cleaned = cleaned[:max_tickers]
    run_date_text = normalize_date(run_date)

    config = load_config()
    project_id = int(config["cloud-id"])
    qc = QCClient()
    qc.push_algorithm(project_id, MAIN_PY)
    compile_id = qc.compile(project_id)
    bt_id = qc.create_backtest(
        project_id,
        compile_id,
        f"Fundamentals_{run_date_text}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        parameters={
            "run_date": run_date_text,
            "tickers": ",".join(cleaned),
            "max_rows": str(len(cleaned)),
        },
    )
    bt_result = qc.wait_for_backtest(project_id, bt_id)
    LAST_BT_FILE.write_text(bt_id, encoding="utf-8")
    rows = decode_rows(bt_result)
    if save_outputs:
        write_outputs(rows, run_date_text)
    return rows
