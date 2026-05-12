"""Download QuantConnect news rows through the QC cloud backtest bridge."""

from __future__ import annotations

import base64
import csv
import io
import json
import zlib
from datetime import date, datetime
from pathlib import Path
from typing import Any

from qc.qc_client import QCClient

ROOT = Path(__file__).resolve().parent
PROJECT_DIR = ROOT / "Z03_NewsAccessTest"
CONFIG_FILE = PROJECT_DIR / "config.json"
MAIN_PY = PROJECT_DIR / "main.py"
OUTPUT_DIR = ROOT / "data" / "news"


def download_news(
    *,
    ticker: str,
    start: date,
    end: date,
    provider: str = "tiingo",
    save_outputs: bool = True,
) -> dict[str, Any]:
    """Run the QC news bridge and return decoded article rows.

    This uses the existing QuantConnect project under `qc/Z03_NewsAccessTest`.
    It should be used for scheduled enrichment jobs, while raw article storage
    remains local CSV plus compact DB summaries.
    """
    provider = provider.lower()
    if provider not in {"tiingo", "benzinga", "both"}:
        raise ValueError("provider must be tiingo, benzinga, or both")
    ticker = ticker.upper()
    start_key = _date_key(start)
    end_key = _date_key(end)

    config = _load_config()
    qc = QCClient()
    project_id = _ensure_project(config)
    qc.push_algorithm(project_id, MAIN_PY)
    compile_id = qc.compile(project_id)
    backtest_id = qc.create_backtest(
        project_id,
        compile_id,
        f"News_{provider}_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        parameters={
            "ticker": ticker,
            "provider": provider,
            "start_date": start_key,
            "end_date": end_key,
        },
    )
    result = qc.wait_for_backtest(project_id, backtest_id, required_prefixes=("NEWS_",))
    rows = decode_news_rows(result)
    output_path = None
    if save_outputs:
        output_path = _write_rows(ticker=ticker, provider=provider, start=start_key, end=end_key, rows=rows)
    return {
        "ticker": ticker,
        "provider": provider,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "project_id": project_id,
        "backtest_id": backtest_id,
        "row_count": len(rows),
        "rows": rows,
        "path": str(output_path) if output_path else None,
    }


def decode_news_rows(backtest_result: dict[str, Any]) -> list[dict[str, str]]:
    stats = backtest_result.get("runtimeStatistics") or {}
    n_chunks = int(stats.get("NEWS_N") or 0)
    if n_chunks <= 0:
        raise ValueError(f"No NEWS chunks found. Runtime statistic keys: {list(stats)[:30]}")
    encoded = "".join(stats.get(f"NEWS_{index:04d}", "") for index in range(n_chunks))
    text = zlib.decompress(base64.b64decode(encoded)).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def _load_config() -> dict[str, Any]:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _ensure_project(config: dict[str, Any]) -> int:
    project_id = config.get("cloud-id")
    if not project_id:
        raise RuntimeError(f"No cloud-id set in {CONFIG_FILE}; create the QC news project first.")
    return int(project_id)


def _write_rows(*, ticker: str, provider: str, start: str, end: str, rows: list[dict[str, str]]) -> Path:
    out_dir = OUTPUT_DIR / ticker.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"news_{provider}_{ticker}_{start}_{end}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["provider", "time", "title", "description", "url", "error"])
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def _date_key(value: date) -> str:
    return value.strftime("%Y%m%d")
