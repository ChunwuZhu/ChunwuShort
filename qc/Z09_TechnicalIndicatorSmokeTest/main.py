# region imports
from AlgorithmImports import *
# endregion

import base64
import csv
import io
import zlib
from datetime import datetime


class Z09TechnicalIndicatorSmokeTest(QCAlgorithm):
    """Export selected daily indicator values for a ticker."""

    _CHUNK = 2000

    def initialize(self):
        ticker = (self.get_parameter("ticker") or "ACM").upper()
        start_str = self.get_parameter("start_date") or "20230512"
        end_str = self.get_parameter("end_date") or "20260508"
        start = datetime.strptime(start_str, "%Y%m%d")
        end = datetime.strptime(end_str, "%Y%m%d")

        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(100000)

        equity = self.add_equity(ticker, Resolution.DAILY)
        equity.set_data_normalization_mode(DataNormalizationMode.RAW)
        self._ticker = ticker
        self._symbol = equity.symbol
        self._rows = []

        self._sma20 = self.sma(self._symbol, 20, Resolution.DAILY)
        self._sma50 = self.sma(self._symbol, 50, Resolution.DAILY)
        self._sma200 = self.sma(self._symbol, 200, Resolution.DAILY)
        self._ema8 = self.ema(self._symbol, 8, Resolution.DAILY)
        self._ema21 = self.ema(self._symbol, 21, Resolution.DAILY)
        self._rsi14 = self.rsi(self._symbol, 14, MovingAverageType.WILDERS, Resolution.DAILY)
        self._atr14 = self.atr(self._symbol, 14, MovingAverageType.WILDERS, Resolution.DAILY)
        self._std20 = self.std(self._symbol, 20, Resolution.DAILY)
        self._std60 = self.std(self._symbol, 60, Resolution.DAILY)
        self.set_warm_up(260, Resolution.DAILY)

    def on_data(self, data: Slice):
        if self.is_warming_up or self._symbol not in data.bars:
            return
        values = [
            self.time.strftime("%Y-%m-%d"),
            self._ticker,
            self._value(self._sma20),
            self._value(self._sma50),
            self._value(self._sma200),
            self._value(self._ema8),
            self._value(self._ema21),
            self._value(self._rsi14),
            self._value(self._atr14),
            self._value(self._std20),
            self._value(self._std60),
        ]
        self._rows.append(",".join(values))

    def on_end_of_algorithm(self):
        header = "date,ticker,sma20,sma50,sma200,ema8,ema21,rsi14,atr14,std20,std60"
        self._emit("TECH", [header] + self._rows)
        self.set_runtime_statistic("META_ticker", self._ticker)
        self.set_runtime_statistic("META_rows", str(len(self._rows)))

    @staticmethod
    def _value(indicator):
        if not indicator.is_ready:
            return ""
        return f"{float(indicator.current.value):.8f}"

    def _emit(self, prefix, rows):
        raw = "\n".join(rows).encode("utf-8")
        encoded = base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")
        n_chunks = max(1, -(-len(encoded) // self._CHUNK))
        self.set_runtime_statistic(f"{prefix}_N", str(n_chunks))
        for i in range(n_chunks):
            self.set_runtime_statistic(f"{prefix}_{i:04d}", encoded[i * self._CHUNK : (i + 1) * self._CHUNK])
