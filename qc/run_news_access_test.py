#!/usr/bin/env python3
"""Smoke-test QuantConnect news dataset access and decode NEWS_* output."""

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

from qc_client import QCClient

ROOT = Path(__file__).parent
PROJECT_DIR = ROOT / "Z03_NewsAccessTest"
CONFIG_FILE = PROJECT_DIR / "config.json"
MAIN_PY = PROJECT_DIR / "main.py"
OUTPUT_DIR = ROOT / "data" / "news_test"


def _norm_date(value: str) -> str:
    text = value.strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text.replace("-", "")
    if len(text) == 8 and text.isdigit():
        return text
    raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD or YYYYMMDD.")


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
    payload = {"name": "A02 News Access Test", "language": "Py"}
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
    n_chunks = int(stats.get("NEWS_N") or 0)
    if n_chunks <= 0:
        raise ValueError(f"No NEWS chunks found. Runtime statistic keys: {list(stats)[:30]}")
    encoded = "".join(stats.get(f"NEWS_{i:04d}", "") for i in range(n_chunks))
    text = zlib.decompress(base64.b64decode(encoded)).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Test QC Benzinga/Tiingo news access.")
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--provider", choices=["both", "benzinga", "tiingo"], default="both")
    parser.add_argument("--start", default="2026-05-01")
    parser.add_argument("--end", default="2026-05-08")
    parser.add_argument("--create-project", action="store_true")
    args = parser.parse_args()

    start = _norm_date(args.start)
    end = _norm_date(args.end)
    config = _load_config()
    qc = QCClient()
    project_id = ensure_project(qc, config, args.create_project)

    print("=" * 60)
    print(f"QC news access test {args.provider} {args.ticker.upper()} {start} -> {end} (project {project_id})")
    print("=" * 60)
    qc.push_algorithm(project_id, MAIN_PY)
    compile_id = qc.compile(project_id)
    bt_id = qc.create_backtest(
        project_id,
        compile_id,
        f"NewsAccess_{args.provider}_{args.ticker.upper()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        parameters={
            "ticker": args.ticker.upper(),
            "provider": args.provider,
            "start_date": start,
            "end_date": end,
        },
    )
    bt_result = qc.wait_for_backtest(project_id, bt_id)
    rows = decode_rows(bt_result)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"news_access_{args.provider}_{args.ticker.upper()}_{start}_{end}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["provider", "time", "title", "description", "url", "error"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nRows: {len(rows)}")
    for row in rows[:20]:
        provider = row.get("provider", "")
        time = row.get("time", "")
        title = row.get("title", "")
        error = row.get("error", "")
        print(f"  {provider} {time} {title or error}")
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
