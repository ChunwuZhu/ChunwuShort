"""Reusable QuantConnect wide option chain downloader."""

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
from qc.parquet_utils import ms_to_utc, write_day_parquet
from qc.qc_client import QCClient

ROOT = Path(__file__).parent
PROJECT_DIR = ROOT / "Z06_OptionChainDownload"
CONFIG_FILE = PROJECT_DIR / "config.json"
MAIN_PY = PROJECT_DIR / "main.py"
OUTPUT_DIR = ROOT / "data"
LAST_BT_FILE = ROOT / ".last_option_chain_bt_id"


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


def ensure_project(qc: QCClient, create_project: bool = False) -> int:
    config = load_config()
    project_id = config.get("cloud-id")
    if project_id:
        return int(project_id)
    if not create_project:
        raise RuntimeError(f"No cloud-id set in {CONFIG_FILE}. Re-run with --create-project.")
    payload = {"name": "A02 Wide Option Chain Download", "language": "Py"}
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


def make_occ(ticker: str, expiry: str, right: str, strike_scaled: int) -> str:
    exp = expiry[2:]
    flag = "C" if right == "call" else "P"
    strike_occ = strike_scaled // 10
    return f"{ticker.upper()}{exp}{flag}{strike_occ:08d}"


def decode_and_save(bt_result: dict, output_dir: Path = OUTPUT_DIR) -> list[Path]:
    stats = bt_result.get("runtimeStatistics") or {}
    ticker = (stats.get("META_ticker") or "UNKNOWN").upper()
    ticker_lower = ticker.lower()
    buckets: dict[str, dict] = {}

    for key, value in stats.items():
        if key.startswith(("T_", "Q_")) and len(key) >= 10:
            parts = key.split("_", 2)
            if len(parts) == 3:
                prefix = f"{parts[0]}_{parts[1]}"
                buckets.setdefault(prefix, {})[parts[2]] = value

    if not buckets:
        print(f"  No T_/Q_ data keys found. Runtime statistic keys: {list(stats.keys())[:20]}")
        return []

    day_rows: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for prefix, chunks in sorted(buckets.items()):
        dtype_code, date_str = prefix.split("_", 1)
        dtype = "trade" if dtype_code == "T" else "quote"
        n_chunks = int(chunks.get("N", 0))
        if n_chunks <= 0:
            continue
        missing = [f"{i:04d}" for i in range(n_chunks) if f"{i:04d}" not in chunks]
        if missing:
            raise ValueError(f"Missing chunks for {prefix}: {missing[:5]}")
        encoded = "".join(chunks[f"{i:04d}"] for i in range(n_chunks))
        text = zlib.decompress(base64.b64decode(encoded)).decode("ascii")
        day_rows[date_str][dtype].extend(text.splitlines())

    saved = []
    dst_dir = output_dir / "option" / "usa" / "minute" / ticker_lower
    dst_dir.mkdir(parents=True, exist_ok=True)

    for date_str, type_map in sorted(day_rows.items()):
        day = parse_day(date_str)
        contracts: dict[str, dict[int, list]] = {}

        def ensure(symbol: str, ms: int) -> None:
            contracts.setdefault(symbol, {}).setdefault(ms, [None, None])

        for row in csv.reader(io.StringIO("\n".join(type_map.get("trade", [])))):
            if len(row) < 9:
                continue
            ms, expiry, right, strike_scaled = int(row[0]), row[1], row[2], int(row[3])
            open_, high, low, close, volume = (int(x) for x in row[4:9])
            symbol = make_occ(ticker, expiry, right, strike_scaled)
            ensure(symbol, ms)
            contracts[symbol][ms][0] = (open_, high, low, close, volume)

        for row in csv.reader(io.StringIO("\n".join(type_map.get("quote", [])))):
            if len(row) < 14:
                continue
            ms, expiry, right, strike_scaled = int(row[0]), row[1], row[2], int(row[3])
            quote_values = tuple(int(x) if x != "" else None for x in row[4:14])
            symbol = make_occ(ticker, expiry, right, strike_scaled)
            ensure(symbol, ms)
            contracts[symbol][ms][1] = quote_values

        rows = []
        for symbol, ts_map in contracts.items():
            for ms, (trade, quote) in sorted(ts_map.items()):
                time_utc = ms_to_utc(day, ms)
                rows.append(
                    (
                        time_utc,
                        symbol,
                        trade[0] if trade else None,
                        trade[1] if trade else None,
                        trade[2] if trade else None,
                        trade[3] if trade else None,
                        trade[4] if trade else None,
                        quote[0] if quote else None,
                        quote[1] if quote else None,
                        quote[2] if quote else None,
                        quote[3] if quote else None,
                        quote[4] if quote else None,
                        quote[5] if quote else None,
                        quote[6] if quote else None,
                        quote[7] if quote else None,
                        quote[8] if quote else None,
                        quote[9] if quote else None,
                    )
                )

        out_path = dst_dir / f"{date_str}.parquet"
        write_day_parquet(out_path, rows)
        print(f"  Saved: {out_path} ({len(contracts)} contracts, {len(rows):,} rows)")
        saved.append(out_path)

    return saved


def download_option_chain(
    *,
    ticker: str,
    start: str | date,
    end: str | date,
    min_strike_rank: int = -250,
    max_strike_rank: int = 250,
    min_dte: int = 0,
    max_dte: int = 180,
    create_project: bool = False,
) -> list[Path]:
    start_text = normalize_date(start)
    end_text = normalize_date(end)
    qc = QCClient()
    project_id = ensure_project(qc, create_project=create_project)
    qc.push_algorithm(project_id, MAIN_PY)
    compile_id = qc.compile(project_id)
    bt_id = qc.create_backtest(
        project_id,
        compile_id,
        f"OptionChain_{ticker.upper()}_{start_text}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        parameters={
            "ticker": ticker.upper(),
            "start_date": start_text,
            "end_date": end_text,
            "min_strike_rank": str(min_strike_rank),
            "max_strike_rank": str(max_strike_rank),
            "min_dte": str(min_dte),
            "max_dte": str(max_dte),
        },
    )
    bt_result = qc.wait_for_backtest(project_id, bt_id)
    LAST_BT_FILE.write_text(bt_id, encoding="utf-8")
    return decode_and_save(bt_result, OUTPUT_DIR)
