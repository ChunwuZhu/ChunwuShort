"""Download QuantConnect equity daily and minute bars into local Parquet."""

from __future__ import annotations

import base64
import csv
import io
import json
import zlib
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from qc.earnings_calendar import normalize_date
from qc.parquet_utils import ms_to_utc, write_equity_parquet
from qc.qc_client import QCClient

ROOT = Path(__file__).parent
PROJECT_DIR = ROOT / "Z08_EquityPriceDownload"
CONFIG_FILE = PROJECT_DIR / "config.json"
MAIN_PY = PROJECT_DIR / "main.py"
OUTPUT_DIR = ROOT / "data"
LAST_BT_FILE = ROOT / ".last_equity_price_bt_id"


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def save_config(config: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(config, indent=4) + "\n", encoding="utf-8")


def project_id_from_response(data: dict) -> int:
    projects = data.get("projects") or []
    if not projects:
        raise RuntimeError(f"Project create response did not contain projects: {data}")
    project = projects[0]
    return int(project.get("projectId") or project.get("project_id") or project.get("id"))


def ensure_project(qc: QCClient) -> int:
    config = load_config()
    project_id = config.get("cloud-id")
    if project_id:
        return int(project_id)
    payload = {"name": "A02 Equity Price Download", "language": "Py"}
    org_id = config.get("organization-id")
    if org_id:
        payload["organizationId"] = org_id
    data = qc.post("projects/create", payload)
    project_id = project_id_from_response(data)
    config["cloud-id"] = project_id
    save_config(config)
    print(f"  Created QC project id={project_id}")
    return project_id


def parse_day(date_str: str) -> date:
    return datetime.strptime(date_str, "%Y%m%d").date()


def decode_and_save(bt_result: dict, output_dir: Path = OUTPUT_DIR) -> dict:
    stats = bt_result.get("runtimeStatistics") or {}
    ticker = (stats.get("META_ticker") or "UNKNOWN").upper()
    ticker_lower = ticker.lower()
    buckets: dict[str, dict] = {}

    for key, value in stats.items():
        if key.startswith(("D_", "M_")) and len(key) >= 5:
            parts = key.split("_", 2)
            if len(parts) == 3:
                prefix = f"{parts[0]}_{parts[1]}"
                buckets.setdefault(prefix, {})[parts[2]] = value

    if not buckets:
        print(f"  No D_/M_ data keys found. Runtime statistic keys: {list(stats.keys())[:20]}")
        return {"ticker": ticker, "files": []}

    decoded: dict[str, list[str]] = {}
    for prefix, chunks in sorted(buckets.items()):
        n_chunks = int(chunks.get("N", 0))
        if n_chunks <= 0:
            continue
        missing = [f"{i:04d}" for i in range(n_chunks) if f"{i:04d}" not in chunks]
        if missing:
            raise ValueError(f"Missing chunks for {prefix}: {missing[:5]}")
        encoded = "".join(chunks[f"{i:04d}"] for i in range(n_chunks))
        text = zlib.decompress(base64.b64decode(encoded)).decode("utf-8")
        decoded[prefix] = text.splitlines()

    files = []
    daily_rows = []
    for row in csv.DictReader(io.StringIO("\n".join(decoded.get("D_ALL", [])))):
        day = parse_day(row["date"])
        daily_rows.append(
            (
                ms_to_utc(day, 0),
                row["symbol"],
                int(row["open"]),
                int(row["high"]),
                int(row["low"]),
                int(row["close"]),
                int(row["volume"]),
            )
        )
    if daily_rows:
        out_path = output_dir / "equity" / "usa" / "daily" / f"{ticker_lower}.parquet"
        write_equity_parquet(out_path, daily_rows)
        files.append(_file_meta(out_path, "daily", len(daily_rows)))
        print(f"  Saved: {out_path} ({len(daily_rows):,} rows)")

    minute_by_day: dict[str, list[tuple]] = defaultdict(list)
    for prefix, lines in decoded.items():
        if not prefix.startswith("M_"):
            continue
        date_str = prefix.split("_", 1)[1]
        day = parse_day(date_str)
        for row in csv.DictReader(io.StringIO("\n".join(lines))):
            minute_by_day[date_str].append(
                (
                    ms_to_utc(day, int(row["ms"])),
                    row["symbol"],
                    int(row["open"]),
                    int(row["high"]),
                    int(row["low"]),
                    int(row["close"]),
                    int(row["volume"]),
                )
            )

    minute_dir = output_dir / "equity" / "usa" / "minute" / ticker_lower
    for date_str, rows in sorted(minute_by_day.items()):
        out_path = minute_dir / f"{date_str}.parquet"
        write_equity_parquet(out_path, rows)
        files.append(_file_meta(out_path, "minute", len(rows), trade_date=date_str))
        print(f"  Saved: {out_path} ({len(rows):,} rows)")

    return {"ticker": ticker, "files": files}


def download_equity_prices(
    *,
    ticker: str,
    daily_start: str | date,
    daily_end: str | date,
    minute_start: str | date,
    minute_end: str | date,
) -> dict:
    daily_start_text = normalize_date(daily_start)
    daily_end_text = normalize_date(daily_end)
    minute_start_text = normalize_date(minute_start)
    minute_end_text = normalize_date(minute_end)

    qc = QCClient()
    project_id = ensure_project(qc)
    qc.push_algorithm(project_id, MAIN_PY)
    compile_id = qc.compile(project_id)
    bt_id = qc.create_backtest(
        project_id,
        compile_id,
        f"EquityPrices_{ticker.upper()}_{minute_start_text}_{minute_end_text}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        parameters={
            "ticker": ticker.upper(),
            "daily_start": daily_start_text,
            "daily_end": daily_end_text,
            "minute_start": minute_start_text,
            "minute_end": minute_end_text,
        },
    )
    bt_result = qc.wait_for_backtest(project_id, bt_id, required_prefixes=("D_", "M_"))
    LAST_BT_FILE.write_text(bt_id, encoding="utf-8")
    result = decode_and_save(bt_result, OUTPUT_DIR)
    result["backtest_id"] = bt_id
    result["daily_start"] = daily_start_text
    result["daily_end"] = daily_end_text
    result["minute_start"] = minute_start_text
    result["minute_end"] = minute_end_text
    return result


def _file_meta(path: Path, resolution: str, row_count: int, trade_date: str | None = None) -> dict:
    return {
        "resolution": resolution,
        "trade_date": trade_date,
        "path": str(path),
        "row_count": row_count,
        "file_size": path.stat().st_size,
    }
