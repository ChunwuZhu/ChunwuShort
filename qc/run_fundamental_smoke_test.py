#!/usr/bin/env python3
"""Test QuantConnect fundamental coverage for earnings tickers."""

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

from qc.earnings_calendar import download_upcoming_earnings, normalize_date
from qc.qc_client import QCClient

ROOT = Path(__file__).parent
PROJECT_DIR = ROOT / "Z04_FundamentalSmokeTest"
CONFIG_FILE = PROJECT_DIR / "config.json"
MAIN_PY = PROJECT_DIR / "main.py"
OUTPUT_DIR = ROOT / "data" / "fundamental_test"


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
    payload = {"name": "A02 Fundamental Smoke Test", "language": "Py"}
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
    n_chunks = int(stats.get("FUNDAMENTALS_N") or 0)
    if n_chunks <= 0:
        raise ValueError(f"No FUNDAMENTALS chunks found. Runtime statistic keys: {list(stats)[:30]}")
    encoded = "".join(stats.get(f"FUNDAMENTALS_{i:04d}", "") for i in range(n_chunks))
    text = zlib.decompress(base64.b64decode(encoded)).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def write_outputs(rows: list[dict], stem: str) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / f"{stem}.csv"
    json_path = OUTPUT_DIR / f"{stem}.json"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["ticker"])
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return csv_path, json_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Test QC fundamentals for earnings tickers.")
    parser.add_argument("--run-date", default="2026-05-08")
    parser.add_argument("--earnings-date", default="2026-05-11")
    parser.add_argument("--tickers", default="", help="Optional comma-separated tickers. If omitted, use QC earnings for --earnings-date.")
    parser.add_argument("--max-tickers", type=int, default=120)
    parser.add_argument("--create-project", action="store_true")
    args = parser.parse_args()

    run_date = normalize_date(args.run_date)
    earnings_date = normalize_date(args.earnings_date)
    if args.tickers.strip():
        tickers = [x.strip().upper() for x in args.tickers.split(",") if x.strip()]
    else:
        earnings = download_upcoming_earnings(
            run_date=run_date,
            start=earnings_date,
            end=earnings_date,
            max_events=10000,
            save_outputs=True,
        )
        tickers = sorted({row["ticker"].upper() for row in earnings if row.get("ticker")})
    tickers = tickers[: args.max_tickers]
    if not tickers:
        raise RuntimeError("No target tickers to test")

    config = _load_config()
    qc = QCClient()
    project_id = ensure_project(qc, config, args.create_project)

    print("=" * 60)
    print(f"QC fundamental smoke test {run_date}; {len(tickers)} tickers from {earnings_date}")
    print("=" * 60)
    qc.push_algorithm(project_id, MAIN_PY)
    compile_id = qc.compile(project_id)
    bt_id = qc.create_backtest(
        project_id,
        compile_id,
        f"FundamentalSmoke_{earnings_date}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        parameters={
            "run_date": run_date,
            "tickers": ",".join(tickers),
            "max_rows": str(len(tickers)),
        },
    )
    bt_result = qc.wait_for_backtest(project_id, bt_id)
    rows = decode_rows(bt_result)
    stem = f"fundamentals_{earnings_date}_{run_date}"
    csv_path, json_path = write_outputs(rows, stem)

    covered = [row for row in rows if row.get("market_cap")]
    eligible = [
        row for row in covered
        if row.get("market_cap") and float(row["market_cap"]) >= 10_000_000_000
    ]
    print(f"\nRows: {len(rows)}")
    print(f"With market_cap: {len(covered)}")
    print(f"Market cap >= 10B: {len(eligible)}")
    for row in eligible[:30]:
        market_cap_b = float(row["market_cap"]) / 1_000_000_000
        print(f"  {row['ticker']:6s} ${market_cap_b:8.1f}B  {row.get('company_name','')}")
    print(f"\nSaved CSV:  {csv_path}")
    print(f"Saved JSON: {json_path}")


if __name__ == "__main__":
    main()
