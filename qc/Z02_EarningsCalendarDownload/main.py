# region imports
from AlgorithmImports import *
# endregion

import base64
import zlib
from datetime import datetime, timedelta


class Z02EarningsCalendarDownload(QCAlgorithm):
    """Export EODHD upcoming earnings events through runtime statistics."""

    _CHUNK = 2000

    def initialize(self):
        run_date_str = self.get_parameter("run_date") or datetime.utcnow().strftime("%Y%m%d")
        start_str = self.get_parameter("start_date") or run_date_str
        end_str = self.get_parameter("end_date")
        max_events = int(self.get_parameter("max_events") or 2000)

        run_date = datetime.strptime(run_date_str, "%Y%m%d")
        start = datetime.strptime(start_str, "%Y%m%d")
        if end_str:
            end = datetime.strptime(end_str, "%Y%m%d")
        else:
            end = start + timedelta(days=14)

        # Run one QC data day and export any upcoming earnings whose
        # ReportDate falls inside the requested report window.
        qc_end = run_date + timedelta(days=1)
        self.set_start_date(run_date.year, run_date.month, run_date.day)
        self.set_end_date(qc_end.year, qc_end.month, qc_end.day)
        self.set_cash(100000)

        self.universe_settings.resolution = Resolution.DAILY
        self.universe_settings.data_normalization_mode = DataNormalizationMode.RAW

        self._start_date = start.date()
        self._end_date = end.date()
        self._max_events = max_events
        self._rows = {}
        self._seen = set()

        self.add_universe(EODHDUpcomingEarnings, self._select_earnings)
        self.log(
            f"Exporting EODHD upcoming earnings as of {run_date.date()} "
            f"for report dates {self._start_date} to {self._end_date}"
        )

    def _select_earnings(self, earnings):
        current_date = self.time.date()
        for datum in earnings:
            if len(self._rows) >= self._max_events:
                break

            report_date = self._to_date(getattr(datum, "report_date", None) or getattr(datum, "ReportDate", None))
            if report_date is None or report_date < self._start_date or report_date > self._end_date:
                continue

            ticker = self._symbol_value(getattr(datum, "symbol", None) or getattr(datum, "Symbol", None))
            report_time = self._value_string(
                getattr(datum, "report_time", None) or getattr(datum, "ReportTime", None)
            )
            estimate = self._to_float(getattr(datum, "estimate", None) or getattr(datum, "Estimate", None))

            key = (ticker, report_date.isoformat(), report_time)
            if not ticker or key in self._seen:
                continue

            self._seen.add(key)
            self._rows[key] = [
                current_date.isoformat(),
                ticker,
                report_date.isoformat(),
                report_time,
                "" if estimate is None else str(estimate),
            ]

        return []

    def on_end_of_algorithm(self):
        self.set_runtime_statistic("META_source", "quantconnect_eodhd_upcoming_earnings")
        self.set_runtime_statistic("META_start_date", self._start_date.isoformat())
        self.set_runtime_statistic("META_end_date", self._end_date.isoformat())
        self.set_runtime_statistic("META_event_count", str(len(self._rows)))

        header = "as_of_date,ticker,report_date,report_time,estimate"
        rows = [header]
        for _, values in sorted(self._rows.items(), key=lambda item: (item[0][1], item[0][0], item[0][2])):
            rows.append(",".join(self._csv(value) for value in values))
        self._emit("EARNINGS", rows)

    def _emit(self, prefix, rows):
        raw = "\n".join(rows).encode("utf-8")
        encoded = base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")
        n_chunks = max(1, -(-len(encoded) // self._CHUNK))
        self.set_runtime_statistic(f"{prefix}_N", str(n_chunks))
        for i in range(n_chunks):
            self.set_runtime_statistic(
                f"{prefix}_{i:04d}",
                encoded[i * self._CHUNK : (i + 1) * self._CHUNK],
            )

    @staticmethod
    def _to_date(value):
        if value is None:
            return None
        if hasattr(value, "date"):
            return value.date()
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except Exception:
            return None

    @staticmethod
    def _to_float(value):
        if value is None:
            return None
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _symbol_value(symbol):
        if symbol is None:
            return ""
        value = getattr(symbol, "value", None) or getattr(symbol, "Value", None)
        if value:
            return str(value).upper()
        text = str(symbol).strip()
        return text.split(" ")[0].upper()

    @staticmethod
    def _value_string(value):
        if value is None:
            return ""
        inner = getattr(value, "value", None) or getattr(value, "Value", None)
        if inner is not None:
            return str(inner)
        return str(value)

    @staticmethod
    def _csv(value):
        text = "" if value is None else str(value)
        if any(ch in text for ch in [",", "\"", "\n"]):
            return "\"" + text.replace("\"", "\"\"") + "\""
        return text
