# region imports
from AlgorithmImports import *
# endregion

import base64
import zlib
from datetime import datetime


class Z08EquityPriceDownload(QCAlgorithm):
    """Export daily history and minute event-window bars for one equity."""

    _CHUNK = 2000

    def initialize(self):
        ticker = (self.get_parameter("ticker") or "AAPL").upper()
        daily_start_str = self.get_parameter("daily_start")
        daily_end_str = self.get_parameter("daily_end")
        minute_start_str = self.get_parameter("minute_start")
        minute_end_str = self.get_parameter("minute_end")
        if not all([daily_start_str, daily_end_str, minute_start_str, minute_end_str]):
            raise ValueError("daily_start, daily_end, minute_start, and minute_end are required")

        self._ticker = ticker
        self._daily_start = datetime.strptime(daily_start_str, "%Y%m%d")
        self._daily_end = datetime.strptime(daily_end_str, "%Y%m%d")
        minute_start = datetime.strptime(minute_start_str, "%Y%m%d")
        minute_end = datetime.strptime(minute_end_str, "%Y%m%d")

        self.set_start_date(minute_start.year, minute_start.month, minute_start.day)
        self.set_end_date(minute_end.year, minute_end.month, minute_end.day)
        self.set_cash(100000)

        equity = self.add_equity(ticker, Resolution.MINUTE)
        equity.set_data_normalization_mode(DataNormalizationMode.RAW)
        self._symbol = equity.symbol
        self._minute_rows = {}
        self._daily_rows = []
        self.log(
            f"Exporting equity prices for {ticker}: daily {daily_start_str}~{daily_end_str}; "
            f"minute {minute_start_str}~{minute_end_str}"
        )

    def on_data(self, data: Slice):
        if self._symbol not in data.bars:
            return
        bar = data.bars[self._symbol]
        date_str = self.time.strftime("%Y%m%d")
        ms = int((self.time.hour * 3600 + self.time.minute * 60 + self.time.second) * 1000)
        self._minute_rows.setdefault(date_str, []).append(
            f"{ms},{self._ticker},"
            f"{int(round(bar.open * 10000))},"
            f"{int(round(bar.high * 10000))},"
            f"{int(round(bar.low * 10000))},"
            f"{int(round(bar.close * 10000))},"
            f"{int(bar.volume)}"
        )

    def on_end_of_algorithm(self):
        self._collect_daily_history()
        self.set_runtime_statistic("META_ticker", self._ticker)
        self.set_runtime_statistic("META_daily_rows", str(len(self._daily_rows)))
        self.set_runtime_statistic("META_minute_days", str(len(self._minute_rows)))
        self._emit("D_ALL", ["date,symbol,open,high,low,close,volume"] + self._daily_rows)
        for date_str, rows in self._minute_rows.items():
            self._emit(f"M_{date_str}", ["ms,symbol,open,high,low,close,volume"] + rows)

    def _collect_daily_history(self):
        history = self.history(self._symbol, self._daily_start, self._daily_end, Resolution.DAILY)
        if history.empty:
            return
        for index, row in history.iterrows():
            timestamp = index[-1] if isinstance(index, tuple) else index
            if hasattr(timestamp, "to_pydatetime"):
                timestamp = timestamp.to_pydatetime()
            date_str = timestamp.strftime("%Y%m%d")
            self._daily_rows.append(
                f"{date_str},{self._ticker},"
                f"{int(round(float(row['open']) * 10000))},"
                f"{int(round(float(row['high']) * 10000))},"
                f"{int(round(float(row['low']) * 10000))},"
                f"{int(round(float(row['close']) * 10000))},"
                f"{int(float(row['volume']))}"
            )

    def _emit(self, prefix, rows):
        raw = "\n".join(rows).encode("utf-8")
        encoded = base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")
        n_chunks = max(1, -(-len(encoded) // self._CHUNK))
        self.set_runtime_statistic(f"{prefix}_N", str(n_chunks))
        for i in range(n_chunks):
            self.set_runtime_statistic(f"{prefix}_{i:04d}", encoded[i * self._CHUNK : (i + 1) * self._CHUNK])
