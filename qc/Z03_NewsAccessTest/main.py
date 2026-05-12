# region imports
from AlgorithmImports import *
# endregion

import base64
import zlib
from datetime import datetime


class Z03NewsAccessTest(QCAlgorithm):
    """Smoke-test QuantConnect BenzingaNews and TiingoNews access."""

    _CHUNK = 2000

    def initialize(self):
        ticker = (self.get_parameter("ticker") or "AAPL").upper()
        provider = (self.get_parameter("provider") or "both").lower()
        start_str = self.get_parameter("start_date") or "20260501"
        end_str = self.get_parameter("end_date") or "20260508"

        start = datetime.strptime(start_str, "%Y%m%d")
        end = datetime.strptime(end_str, "%Y%m%d")
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(100000)

        self._ticker = ticker
        self._rows = []
        self._providers = []

        equity = self.add_equity(ticker, Resolution.DAILY).symbol
        if provider in ("both", "benzinga"):
            try:
                symbol = self.add_data(BenzingaNews, ticker, Resolution.DAILY).symbol
                self._providers.append(("benzinga", symbol))
            except Exception as exc:
                self._rows.append(["benzinga", "SUBSCRIBE_ERROR", "", "", "", str(exc)])

        if provider in ("both", "tiingo"):
            try:
                symbol = self.add_data(TiingoNews, ticker, Resolution.DAILY).symbol
                self._providers.append(("tiingo", symbol))
            except Exception as exc:
                self._rows.append(["tiingo", "SUBSCRIBE_ERROR", "", "", "", str(exc)])

        self.log(f"Testing news access for {ticker} / {equity} using {provider}")

    def on_data(self, slice):
        for provider, symbol in self._providers:
            if provider == "benzinga":
                articles = slice.get(BenzingaNews)
            else:
                articles = slice.get(TiingoNews)
            article = articles.get(symbol) if articles else None
            if not article:
                continue
            self._rows.append([
                provider,
                self.time.isoformat(),
                self._field(article, "title"),
                self._field(article, "description") or self._field(article, "contents"),
                self._field(article, "url"),
                "",
            ])

    def on_end_of_algorithm(self):
        self.set_runtime_statistic("META_ticker", self._ticker)
        self.set_runtime_statistic("META_row_count", str(len(self._rows)))
        header = "provider,time,title,description,url,error"
        rows = [header]
        for row in self._rows:
            rows.append(",".join(self._csv(value) for value in row))
        self._emit("NEWS", rows)

    def _emit(self, prefix, rows):
        raw = "\n".join(rows).encode("utf-8")
        encoded = base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")
        n_chunks = max(1, -(-len(encoded) // self._CHUNK))
        self.set_runtime_statistic(f"{prefix}_N", str(n_chunks))
        for i in range(n_chunks):
            self.set_runtime_statistic(f"{prefix}_{i:04d}", encoded[i * self._CHUNK : (i + 1) * self._CHUNK])

    @staticmethod
    def _field(article, name):
        value = getattr(article, name, None) or getattr(article, name.capitalize(), None)
        return "" if value is None else str(value)

    @staticmethod
    def _csv(value):
        text = "" if value is None else str(value)
        if any(ch in text for ch in [",", "\"", "\n"]):
            return "\"" + text.replace("\"", "\"\"") + "\""
        return text
