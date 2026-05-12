"""Shared QuantConnect Cloud REST API client."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

QC_API = "https://www.quantconnect.com/api/v2"


class QCClient:
    """Thin wrapper around the QC Cloud REST API (no Docker required)."""

    def __init__(self):
        creds_path = Path.home() / ".lean" / "credentials"
        try:
            creds = json.loads(creds_path.read_text())
        except FileNotFoundError:
            raise FileNotFoundError(
                f"QC credentials not found at {creds_path}. "
                "Create it with: {\"user-id\": \"...\", \"api-token\": \"...\"}"
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {creds_path}: {e}")
        self.user_id   = str(creds["user-id"])
        self.api_token = creds["api-token"]

    def _auth(self) -> tuple[dict, tuple]:
        ts = str(int(time.time()))
        h  = hashlib.sha256(f"{self.api_token}:{ts}".encode()).hexdigest()
        return {"Timestamp": ts}, (self.user_id, h)

    def post(self, endpoint: str, payload: dict) -> dict:
        headers, auth = self._auth()
        r = requests.post(f"{QC_API}/{endpoint}", json=payload,
                          headers=headers, auth=auth, timeout=120)
        r.raise_for_status()
        data = r.json()
        if not data.get("success", False):
            raise RuntimeError(f"{endpoint} failed: {data}")
        return data

    def push_algorithm(self, project_id: int, path: Path) -> None:
        content = path.read_text(encoding="utf-8")
        try:
            self.post("files/update", {"projectId": project_id,
                                       "name": path.name, "content": content})
            print(f"  Updated {path.name}")
        except RuntimeError:
            self.post("files/create", {"projectId": project_id,
                                       "name": path.name, "content": content})
            print(f"  Created {path.name}")

    def compile(self, project_id: int) -> str:
        print("  Compiling … ", end="", flush=True)
        data       = self.post("compile/create", {"projectId": project_id})
        compile_id = data["compileId"]
        for _ in range(60):
            time.sleep(5)
            d     = self.post("compile/read",
                              {"projectId": project_id, "compileId": compile_id})
            state = d.get("state", "")
            if state == "BuildSuccess":
                print("OK")
                return compile_id
            if state == "BuildError":
                raise RuntimeError("Compile failed:\n" + "\n".join(d.get("logs", [])))
        raise TimeoutError("Compile timed out")

    def wait_for_idle(self, project_id: int, poll_interval: int = 15) -> None:
        """Block until no backtests are running on this project's cluster."""
        import time as _time
        for _ in range(60):
            d = self.post("backtests/list", {"projectId": project_id})
            running = [bt for bt in d.get("backtests", []) if not bt.get("completed")]
            if not running:
                return
            print(f"  Waiting for {len(running)} running backtest(s) to finish...")
            _time.sleep(poll_interval)
        raise TimeoutError("Timed out waiting for cluster to become idle")

    def create_backtest(self, project_id: int, compile_id: str,
                        name: str, parameters: dict[str, str]) -> str:
        print(f"  Creating backtest '{name}' … ", end="", flush=True)
        data  = self.post("backtests/create", {
            "projectId": project_id, "compileId": compile_id,
            "backtestName": name, "parameters": parameters,
        })
        bt_id = data["backtest"]["backtestId"]
        print(f"id={bt_id}")
        return bt_id

    def wait_for_backtest(self, project_id: int, bt_id: str,
                          poll_interval: int = 10,
                          required_prefixes: tuple[str, ...] | None = None) -> dict:
        """Poll until the backtest completes; return the backtest dict."""
        print("  Running ", end="", flush=True)
        for _ in range(180):
            time.sleep(poll_interval)
            d        = self.post("backtests/read",
                                 {"projectId": project_id, "backtestId": bt_id})
            bt       = d.get("backtest", {})
            progress = bt.get("progress", 0)
            status   = bt.get("status", "")
            print(f"\r  Running … {int(progress * 100):3d}%  [{status}]",
                  end="", flush=True)
            if bt.get("completed"):
                # Wait for custom runtimeStatistics keys to propagate.
                for _ in range(24):
                    time.sleep(5)
                    d  = self.post("backtests/read",
                                   {"projectId": project_id, "backtestId": bt_id})
                    bt = d.get("backtest", {})
                    stats = bt.get("runtimeStatistics") or {}
                    if required_prefixes:
                        if all(any(k.startswith(prefix) for k in stats) for prefix in required_prefixes):
                            break
                    elif any(k.startswith(("T_", "Q_", "EARNINGS_", "NEWS_", "FUNDAMENTALS_", "HISTEARN_"))
                             for k in stats):
                        break
                print("  ✓")
                return bt
            if status.lower().replace(" ", "") in ("runtimeerror", "error"):
                raise RuntimeError(f"Backtest failed: {bt.get('error', '')}")
        raise TimeoutError("Backtest timed out after 30 min")
