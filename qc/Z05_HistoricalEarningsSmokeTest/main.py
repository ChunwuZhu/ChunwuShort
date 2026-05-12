# region imports
from AlgorithmImports import *
# endregion

import base64
import zlib
from datetime import datetime


class Z05HistoricalEarningsSmokeTest(QCAlgorithm):
    """Record changes in Morningstar EarningReports fields for one ticker."""

    _CHUNK = 2000

    def initialize(self):
        self._ticker = (self.get_parameter("ticker") or "CEG").upper()
        start_str = self.get_parameter("start_date") or "20230101"
        end_str = self.get_parameter("end_date") or "20260508"

        start = datetime.strptime(start_str, "%Y%m%d")
        end = datetime.strptime(end_str, "%Y%m%d")
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(100000)

        self.universe_settings.resolution = Resolution.DAILY
        self._last_key = None
        self._rows = []
        self.add_universe(self._coarse, self._fine)
        self.log(f"Testing historical EarningReports for {self._ticker} from {start_str} to {end_str}")

    def _coarse(self, coarse):
        for item in coarse:
            ticker = self._symbol_value(getattr(item, "symbol", None) or getattr(item, "Symbol", None))
            has_fundamental = bool(
                getattr(item, "has_fundamental_data", None)
                if getattr(item, "has_fundamental_data", None) is not None
                else getattr(item, "HasFundamentalData", False)
            )
            if ticker == self._ticker and has_fundamental:
                return [item.Symbol]
        return []

    def _fine(self, fine):
        for item in fine:
            ticker = self._symbol_value(getattr(item, "symbol", None) or getattr(item, "Symbol", None))
            if ticker != self._ticker:
                continue
            reports = self._get_obj(item, "earning_reports", "EarningReports")
            row = {
                "observed_date": self.time.date().isoformat(),
                "ticker": ticker,
                "file_date": self._metric(reports, ["file_date", "FileDate"]),
                "period_ending_date": self._metric(reports, ["period_ending_date", "PeriodEndingDate"]),
                "basic_eps_3m": self._metric(reports, ["basic_eps", "BasicEPS"], period_names=("three_months", "ThreeMonths")),
                "basic_eps_ttm": self._metric(reports, ["basic_eps", "BasicEPS"], period_names=("twelve_months", "TwelveMonths")),
                "diluted_eps_3m": self._metric(reports, ["diluted_eps", "DilutedEPS"], period_names=("three_months", "ThreeMonths")),
                "diluted_eps_ttm": self._metric(reports, ["diluted_eps", "DilutedEPS"], period_names=("twelve_months", "TwelveMonths")),
            }
            key = (
                row["file_date"],
                row["period_ending_date"],
                row["basic_eps_3m"],
                row["basic_eps_ttm"],
                row["diluted_eps_3m"],
                row["diluted_eps_ttm"],
            )
            if key != self._last_key:
                self._rows.append(row)
                self._last_key = key
        return []

    def on_end_of_algorithm(self):
        self.set_runtime_statistic("META_ticker", self._ticker)
        self.set_runtime_statistic("META_row_count", str(len(self._rows)))
        header = [
            "observed_date",
            "ticker",
            "file_date",
            "period_ending_date",
            "basic_eps_3m",
            "basic_eps_ttm",
            "diluted_eps_3m",
            "diluted_eps_ttm",
        ]
        rows = [",".join(header)]
        for row in self._rows:
            rows.append(",".join(self._csv(row.get(name, "")) for name in header))
        self._emit("HISTEARN", rows)

    def _emit(self, prefix, rows):
        raw = "\n".join(rows).encode("utf-8")
        encoded = base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")
        n_chunks = max(1, -(-len(encoded) // self._CHUNK))
        self.set_runtime_statistic(f"{prefix}_N", str(n_chunks))
        for i in range(n_chunks):
            self.set_runtime_statistic(f"{prefix}_{i:04d}", encoded[i * self._CHUNK : (i + 1) * self._CHUNK])

    @staticmethod
    def _get_obj(obj, *names):
        if obj is None:
            return None
        for name in names:
            value = getattr(obj, name, None)
            if value is not None:
                return value
        return None

    @classmethod
    def _metric(cls, obj, names, period_names=("value", "Value")):
        metric = cls._get_obj(obj, *names)
        if metric is None:
            return ""
        value = cls._get_obj(metric, *period_names)
        return cls._clean_value(value if value is not None else metric)

    @staticmethod
    def _clean_value(value):
        if value is None:
            return ""
        if hasattr(value, "date"):
            return value.date().isoformat()
        if hasattr(value, "value"):
            return value.value
        if hasattr(value, "Value"):
            return value.Value
        text = str(value)
        if text.lower() in {"nan", "none"}:
            return ""
        return text

    @staticmethod
    def _symbol_value(symbol):
        if symbol is None:
            return ""
        value = getattr(symbol, "value", None) or getattr(symbol, "Value", None)
        if value:
            return str(value).upper()
        return str(symbol).strip().split(" ")[0].upper()

    @staticmethod
    def _csv(value):
        text = "" if value is None else str(value)
        if any(ch in text for ch in [",", "\"", "\n"]):
            return "\"" + text.replace("\"", "\"\"") + "\""
        return text
