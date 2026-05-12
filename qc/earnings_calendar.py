"""Reusable QuantConnect upcoming earnings downloader."""

from __future__ import annotations

import base64
import csv
import io
import json
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path

from qc.qc_client import QCClient

ROOT = Path(__file__).parent
PROJECT_DIR = ROOT / "Z02_EarningsCalendarDownload"
CONFIG_FILE = PROJECT_DIR / "config.json"
MAIN_PY = PROJECT_DIR / "main.py"
OUTPUT_DIR = ROOT / "data" / "earnings"
LAST_BT_FILE = ROOT / ".last_earnings_bt_id"


def normalize_date(value: str | date) -> str:
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = value.strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text.replace("-", "")
    if len(text) == 8 and text.isdigit():
        return text
    raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD or YYYYMMDD.")


def previous_weekday(day: date) -> date:
    current = day
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def default_run_date(today: date | None = None) -> str:
    return previous_weekday(today or date.today()).strftime("%Y%m%d")


def default_start(run_date_yyyymmdd: str) -> str:
    run_date = datetime.strptime(run_date_yyyymmdd, "%Y%m%d").date()
    return (run_date + timedelta(days=1)).strftime("%Y%m%d")


def default_end(start_yyyymmdd: str, days: int) -> str:
    start = datetime.strptime(start_yyyymmdd, "%Y%m%d").date()
    return (start + timedelta(days=days)).strftime("%Y%m%d")


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def decode_rows(bt_result: dict) -> list[dict]:
    stats = bt_result.get("runtimeStatistics") or {}
    n_chunks = int(stats.get("EARNINGS_N") or 0)
    if n_chunks <= 0:
        raise ValueError(f"No EARNINGS chunks found. Runtime statistic keys: {list(stats)[:20]}")
    encoded = "".join(stats.get(f"EARNINGS_{i:04d}", "") for i in range(n_chunks))
    text = zlib.decompress(base64.b64decode(encoded)).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def write_outputs(rows: list[dict], start: str, end: str) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"qc_earnings_{start}_{end}"
    csv_path = OUTPUT_DIR / f"{stem}.csv"
    json_path = OUTPUT_DIR / f"{stem}.json"
    fieldnames = ["as_of_date", "ticker", "report_date", "report_time", "estimate"]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return csv_path, json_path


def download_upcoming_earnings(
    *,
    run_date: str | date | None = None,
    start: str | date | None = None,
    end: str | date | None = None,
    days: int = 7,
    max_events: int = 10000,
    save_outputs: bool = True,
) -> list[dict]:
    run_date_text = normalize_date(run_date) if run_date else default_run_date()
    start_text = normalize_date(start) if start else default_start(run_date_text)
    end_text = normalize_date(end) if end else default_end(start_text, days)
    if start_text > end_text:
        raise ValueError("start must be on or before end")

    config = load_config()
    project_id = int(config["cloud-id"])
    qc = QCClient()
    qc.push_algorithm(project_id, MAIN_PY)
    compile_id = qc.compile(project_id)
    bt_id = qc.create_backtest(
        project_id,
        compile_id,
        f"EarningsCalendar_{start_text}_{end_text}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        parameters={
            "start_date": start_text,
            "end_date": end_text,
            "run_date": run_date_text,
            "max_events": str(max_events),
        },
    )
    bt_result = qc.wait_for_backtest(project_id, bt_id)
    LAST_BT_FILE.write_text(bt_id, encoding="utf-8")
    rows = decode_rows(bt_result)
    if save_outputs:
        write_outputs(rows, start_text, end_text)
    return rows
