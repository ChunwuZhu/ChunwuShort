# region imports
from AlgorithmImports import *
# endregion

import base64
import zlib
from datetime import datetime


class Z06OptionChainDownload(QCAlgorithm):
    """Export minute-resolution wide option chain trade and quote bars."""

    _CHUNK = 2000

    def initialize(self):
        ticker = (self.get_parameter("ticker") or "QQQ").upper()
        start_str = self.get_parameter("start_date") or "20260424"
        end_str = self.get_parameter("end_date") or "20260424"
        min_strike = int(self.get_parameter("min_strike_rank") or -250)
        max_strike = int(self.get_parameter("max_strike_rank") or 250)
        min_dte = int(self.get_parameter("min_dte") or 0)
        max_dte = int(self.get_parameter("max_dte") or 180)

        start = datetime.strptime(start_str, "%Y%m%d")
        end = datetime.strptime(end_str, "%Y%m%d")
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(100000)

        self._ticker = ticker
        self.add_equity(ticker, Resolution.MINUTE)
        option = self.add_option(ticker, Resolution.MINUTE)
        option.set_filter(
            lambda universe: universe.include_weeklys()
            .strikes(min_strike, max_strike)
            .expiration(min_dte, max_dte)
        )
        self._option_symbol = option.symbol
        self._trade_rows = {}
        self._quote_rows = {}

        self.log(
            f"Collecting wide option chain for {ticker} {start_str}~{end_str}; "
            f"strikes={min_strike}:{max_strike}, dte={min_dte}:{max_dte}"
        )

    def on_data(self, data: Slice):
        if self._option_symbol not in data.option_chains:
            return

        date_str = self.time.strftime("%Y%m%d")
        ms = int((self.time.hour * 3600 + self.time.minute * 60 + self.time.second) * 1000)
        chain = data.option_chains[self._option_symbol]

        for contract in chain:
            symbol = contract.symbol
            expiry = contract.expiry.strftime("%Y%m%d")
            right = "call" if contract.right == OptionRight.Call else "put"
            strike_scaled = int(round(contract.strike * 10000))

            if symbol in data.bars:
                bar = data.bars[symbol]
                self._trade_rows.setdefault(date_str, []).append(
                    f"{ms},{expiry},{right},{strike_scaled},"
                    f"{int(round(bar.open * 10000))},"
                    f"{int(round(bar.high * 10000))},"
                    f"{int(round(bar.low * 10000))},"
                    f"{int(round(bar.close * 10000))},"
                    f"{int(bar.volume)}"
                )

            if symbol in data.quote_bars:
                quote = data.quote_bars[symbol]
                bid = quote.bid
                ask = quote.ask
                self._quote_rows.setdefault(date_str, []).append(
                    f"{ms},{expiry},{right},{strike_scaled},"
                    f"{self._scaled(bid.open if bid else None)},"
                    f"{self._scaled(bid.high if bid else None)},"
                    f"{self._scaled(bid.low if bid else None)},"
                    f"{self._scaled(bid.close if bid else None)},"
                    f"{int(quote.last_bid_size)},"
                    f"{self._scaled(ask.open if ask else None)},"
                    f"{self._scaled(ask.high if ask else None)},"
                    f"{self._scaled(ask.low if ask else None)},"
                    f"{self._scaled(ask.close if ask else None)},"
                    f"{int(quote.last_ask_size)}"
                )

    def on_end_of_algorithm(self):
        self.set_runtime_statistic("META_ticker", self._ticker)
        for date_str, rows in self._trade_rows.items():
            self._emit(f"T_{date_str}", rows)
        for date_str, rows in self._quote_rows.items():
            self._emit(f"Q_{date_str}", rows)

    def _emit(self, prefix, rows):
        raw = "\n".join(rows).encode("ascii")
        encoded = base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")
        n_chunks = max(1, -(-len(encoded) // self._CHUNK))
        self.set_runtime_statistic(f"{prefix}_N", str(n_chunks))
        for i in range(n_chunks):
            self.set_runtime_statistic(f"{prefix}_{i:04d}", encoded[i * self._CHUNK : (i + 1) * self._CHUNK])
        self.log(
            f"Emitted {prefix}: {len(rows)} rows -> {n_chunks} chunks "
            f"({len(raw) // 1024} KB raw)"
        )

    @staticmethod
    def _scaled(value):
        if value is None:
            return ""
        return int(round(value * 10000))
