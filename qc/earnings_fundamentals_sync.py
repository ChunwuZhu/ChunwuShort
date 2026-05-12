"""Combined QuantConnect upcoming earnings and fundamental downloader."""

from __future__ import annotations

import base64
import csv
import io
import json
import zlib
from datetime import date, datetime
from pathlib import Path

from qc.earnings_calendar import default_end, default_run_date, normalize_date
from qc.qc_client import QCClient

ROOT = Path(__file__).parent
PROJECT_DIR = ROOT / "Z07_EarningsFundamentalsSync"
CONFIG_FILE = PROJECT_DIR / "config.json"
MAIN_PY = PROJECT_DIR / "main.py"
OUTPUT_DIR = ROOT / "data" / "combined_sync"
LAST_BT_FILE = ROOT / ".last_combined_sync_bt_id"


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
    payload = {"name": "A02 Earnings Fundamentals Sync", "language": "Py"}
    org_id = config.get("organization-id")
    if org_id:
        payload["organizationId"] = org_id
    data = qc.post("projects/create", payload)
    project_id = project_id_from_response(data)
    config["cloud-id"] = project_id
    save_config(config)
    print(f"  Created QC project id={project_id}")
    return project_id


def decode_rows(bt_result: dict, prefix: str) -> list[dict]:
    stats = bt_result.get("runtimeStatistics") or {}
    n_chunks = int(stats.get(f"{prefix}_N") or 0)
    if n_chunks <= 0:
        raise ValueError(f"No {prefix} chunks found. Runtime statistic keys: {list(stats)[:30]}")
    encoded = "".join(stats.get(f"{prefix}_{i:04d}", "") for i in range(n_chunks))
    text = zlib.decompress(base64.b64decode(encoded)).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def write_outputs(earnings_rows: list[dict], fundamental_rows: list[dict], start: str, end: str) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"qc_combined_{start}_{end}"
    earnings_path = OUTPUT_DIR / f"{stem}_earnings.json"
    fundamentals_path = OUTPUT_DIR / f"{stem}_fundamentals.json"
    earnings_path.write_text(json.dumps(earnings_rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    fundamentals_path.write_text(json.dumps(fundamental_rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return earnings_path, fundamentals_path


def download_earnings_and_fundamentals(
    *,
    run_date: str | date | None = None,
    start: str | date | None = None,
    end: str | date | None = None,
    days: int = 60,
    max_events: int = 10000,
    max_fundamentals: int = 1000,
    save_outputs: bool = True,
) -> tuple[list[dict], list[dict]]:
    run_date_text = normalize_date(run_date) if run_date else default_run_date()
    start_text = normalize_date(start) if start else run_date_text
    end_text = normalize_date(end) if end else default_end(start_text, days)
    if start_text > end_text:
        raise ValueError("start must be on or before end")

    qc = QCClient()
    project_id = ensure_project(qc)
    qc.push_algorithm(project_id, MAIN_PY)
    compile_id = qc.compile(project_id)
    bt_id = qc.create_backtest(
        project_id,
        compile_id,
        f"EarningsFundamentals_{start_text}_{end_text}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        parameters={
            "run_date": run_date_text,
            "start_date": start_text,
            "end_date": end_text,
            "max_events": str(max_events),
            "max_fundamentals": str(max_fundamentals),
        },
    )
    bt_result = qc.wait_for_backtest(project_id, bt_id, required_prefixes=("EARNINGS_", "FUNDAMENTALS_"))
    LAST_BT_FILE.write_text(bt_id, encoding="utf-8")

    earnings_rows = decode_rows(bt_result, "EARNINGS")
    fundamental_rows = decode_rows(bt_result, "FUNDAMENTALS")
    if save_outputs:
        write_outputs(earnings_rows, fundamental_rows, start_text, end_text)
    return earnings_rows, fundamental_rows
