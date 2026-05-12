#!/usr/bin/env python3
"""Test whether QC fundamental data can provide historical earnings anchors."""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import sys
import zlib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qc.earnings_calendar import normalize_date
from qc.qc_client import QCClient

ROOT = Path(__file__).parent
PROJECT_DIR = ROOT / "Z05_HistoricalEarningsSmokeTest"
CONFIG_FILE = PROJECT_DIR / "config.json"
MAIN_PY = PROJECT_DIR / "main.py"
OUTPUT_DIR = ROOT / "data" / "historical_earnings_test"


def _load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _save_config(config: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(config, indent=4) + "\n", encoding="utf-8")


def _project_id_from_response(data: dict) -> int:
    projects = data.get("projects") or []
    if not projects:
        raise RuntimeError(f"Project create response did not contain projects: {data}")
    project = projects[0]
    return int(project.get("projectId") or project.get("project_id") or project.get("id"))


def ensure_project(qc: QCClient, config: dict, create_project: bool) -> int:
    project_id = config.get("cloud-id")
    if project_id:
        return int(project_id)
    if not create_project:
        raise RuntimeError(f"No cloud-id set in {CONFIG_FILE}. Re-run with --create-project.")
    payload = {"name": "A02 Historical Earnings Smoke Test", "language": "Py"}
    org_id = config.get("organization-id")
    if org_id:
        payload["organizationId"] = org_id
    data = qc.post("projects/create", payload)
    project_id = _project_id_from_response(data)
    config["cloud-id"] = project_id
    _save_config(config)
    print(f"  Created QC project id={project_id}")
    return project_id


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Test QC historical earnings anchors.")
    parser.add_argument("--ticker", default="CEG")
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="2026-05-08")
    parser.add_argument("--create-project", action="store_true")
    args = parser.parse_args()

    ticker = args.ticker.upper()
    start = normalize_date(args.start)
    end = normalize_date(args.end)
    config = _load_config()
    qc = QCClient()
    project_id = ensure_project(qc, config, args.create_project)

    print("=" * 60)
    print(f"QC historical earnings smoke test {ticker} {start} -> {end}")
    print("=" * 60)
    qc.push_algorithm(project_id, MAIN_PY)
    compile_id = qc.compile(project_id)
    bt_id = qc.create_backtest(
        project_id,
        compile_id,
        f"HistEarn_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        parameters={"ticker": ticker, "start_date": start, "end_date": end},
    )
    bt_result = qc.wait_for_backtest(project_id, bt_id)
    rows = decode_rows(bt_result)
    csv_path, json_path = write_outputs(rows, ticker, start, end)

    print(f"\nRows: {len(rows)}")
    for row in rows[-12:]:
        print(
            f"  observed={row.get('observed_date')} "
            f"file={row.get('file_date')} "
            f"period={row.get('period_ending_date')} "
            f"eps3m={row.get('basic_eps_3m')}"
        )
    print(f"\nSaved CSV:  {csv_path}")
    print(f"Saved JSON: {json_path}")


if __name__ == "__main__":
    main()
