# region imports
from AlgorithmImports import *
# endregion

import base64
import zlib
from datetime import datetime, timedelta


class Z07EarningsFundamentalsSync(QCAlgorithm):
    """Export upcoming earnings and matching FineFundamental rows in one backtest."""

    _CHUNK = 2000

    def initialize(self):
        run_date_str = self.get_parameter("run_date") or datetime.utcnow().strftime("%Y%m%d")
        start_str = self.get_parameter("start_date") or run_date_str
        end_str = self.get_parameter("end_date")
        self._max_events = int(self.get_parameter("max_events") or 10000)
        self._max_fundamentals = int(self.get_parameter("max_fundamentals") or 1000)

        run_date = datetime.strptime(run_date_str, "%Y%m%d")
        start = datetime.strptime(start_str, "%Y%m%d")
        end = datetime.strptime(end_str, "%Y%m%d") if end_str else start + timedelta(days=60)
        qc_end = run_date + timedelta(days=1)

        self.set_start_date(run_date.year, run_date.month, run_date.day)
        self.set_end_date(qc_end.year, qc_end.month, qc_end.day)
        self.set_cash(100000)

        self.universe_settings.resolution = Resolution.DAILY
        self.universe_settings.data_normalization_mode = DataNormalizationMode.RAW

        self._run_date = run_date.date()
        self._start_date = start.date()
        self._end_date = end.date()
        self._earnings_rows = {}
        self._earnings_seen = set()
        self._earnings_tickers = set()
        self._fundamental_rows = {}

        self.add_universe(EODHDUpcomingEarnings, self._select_earnings)
        self.add_universe(self._coarse, self._fine)
        self.log(
            f"Combined earnings/fundamentals sync as of {self._run_date}; "
            f"report dates {self._start_date} to {self._end_date}"
        )

    def _select_earnings(self, earnings):
        for datum in earnings:
            if len(self._earnings_rows) >= self._max_events:
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
            if not ticker or key in self._earnings_seen:
                continue

            self._earnings_seen.add(key)
            self._earnings_tickers.add(ticker)
            self._earnings_rows[key] = [
                self._run_date.isoformat(),
                ticker,
                report_date.isoformat(),
                report_time,
                "" if estimate is None else str(estimate),
            ]

        return []

    def _coarse(self, coarse):
        if not self._earnings_tickers:
            return []
        selected = []
        for item in coarse:
            ticker = self._symbol_value(getattr(item, "symbol", None) or getattr(item, "Symbol", None))
            has_fundamental = bool(
                getattr(item, "has_fundamental_data", None)
                if getattr(item, "has_fundamental_data", None) is not None
                else getattr(item, "HasFundamentalData", False)
            )
            if ticker in self._earnings_tickers and has_fundamental:
                selected.append(item.Symbol)
            if len(selected) >= self._max_fundamentals:
                break
        return selected

    def _fine(self, fine):
        for item in fine:
            ticker = self._symbol_value(getattr(item, "symbol", None) or getattr(item, "Symbol", None))
            if ticker not in self._earnings_tickers:
                continue
            self._fundamental_rows[ticker] = self._fundamental_row(item)
        return []

    def on_end_of_algorithm(self):
        self.set_runtime_statistic("META_source", "quantconnect_combined_earnings_fundamentals")
        self.set_runtime_statistic("META_start_date", self._start_date.isoformat())
        self.set_runtime_statistic("META_end_date", self._end_date.isoformat())
        self.set_runtime_statistic("META_event_count", str(len(self._earnings_rows)))
        self.set_runtime_statistic("META_fundamental_count", str(len(self._fundamental_rows)))
        self._emit_earnings()
        self._emit_fundamentals()

    def _emit_earnings(self):
        rows = ["as_of_date,ticker,report_date,report_time,estimate"]
        for _, values in sorted(self._earnings_rows.items(), key=lambda item: (item[0][1], item[0][0], item[0][2])):
            rows.append(",".join(self._csv(value) for value in values))
        self._emit("EARNINGS", rows)

    def _emit_fundamentals(self):
        header = [
            "ticker",
            "company_name",
            "market_cap",
            "sector_code",
            "industry_group_code",
            "industry_code",
            "exchange_id",
            "security_type",
            "country_id",
            "currency_id",
            "primary_share_class_id",
            "shares_outstanding",
            "pe_ratio",
            "forward_pe_ratio",
            "pb_ratio",
            "ps_ratio",
            "pcf_ratio",
            "dividend_yield",
            "ev_to_ebitda",
            "ev_to_revenue",
            "revenue_ttm",
            "gross_profit_ttm",
            "operating_income_ttm",
            "net_income_ttm",
            "eps_ttm",
            "roe",
            "roa",
            "debt_to_equity",
            "current_ratio",
            "quick_ratio",
            "asset_turnover",
            "gross_margin",
            "operating_margin",
            "net_margin",
        ]
        rows = [",".join(header)]
        for ticker in sorted(self._earnings_tickers):
            values = self._fundamental_rows.get(ticker) or {"ticker": ticker}
            rows.append(",".join(self._csv(values.get(name, "")) for name in header))
        self._emit("FUNDAMENTALS", rows)

    def _fundamental_row(self, item):
        company_ref = self._get_obj(item, "company_reference", "CompanyReference")
        company_profile = self._get_obj(item, "company_profile", "CompanyProfile")
        asset_class = self._get_obj(item, "asset_classification", "AssetClassification")
        security_ref = self._get_obj(item, "security_reference", "SecurityReference")
        valuation = self._get_obj(item, "valuation_ratios", "ValuationRatios")
        earning_reports = self._get_obj(item, "earning_reports", "EarningReports")
        operation = self._get_obj(item, "operation_ratios", "OperationRatios")
        financials = self._get_obj(item, "financial_statements", "FinancialStatements")

        income = self._get_obj(financials, "income_statement", "IncomeStatement")
        return {
            "ticker": self._symbol_value(getattr(item, "symbol", None) or getattr(item, "Symbol", None)),
            "company_name": self._first_value(company_ref, ["standard_name", "StandardName", "company_name", "CompanyName"]),
            "market_cap": self._first_value(company_profile, ["market_cap", "MarketCap"])
            or self._first_value(item, ["market_cap", "MarketCap"]),
            "sector_code": self._first_value(asset_class, ["morningstar_sector_code", "MorningstarSectorCode"]),
            "industry_group_code": self._first_value(asset_class, ["morningstar_industry_group_code", "MorningstarIndustryGroupCode"]),
            "industry_code": self._first_value(asset_class, ["morningstar_industry_code", "MorningstarIndustryCode"]),
            "exchange_id": self._first_value(security_ref, ["exchange_id", "ExchangeId"]),
            "security_type": self._first_value(security_ref, ["security_type", "SecurityType"]),
            "country_id": self._first_value(company_ref, ["country_id", "CountryId"]),
            "currency_id": self._first_value(security_ref, ["currency_id", "CurrencyId"]),
            "primary_share_class_id": self._first_value(company_ref, ["primary_share_class_id", "PrimaryShareClassID", "PrimaryShareClassId"]),
            "shares_outstanding": self._metric(company_profile, ["shares_outstanding", "SharesOutstanding"]),
            "pe_ratio": self._first_value(valuation, ["pe_ratio", "PERatio"]),
            "forward_pe_ratio": self._first_value(valuation, ["forward_pe_ratio", "ForwardPERatio"]),
            "pb_ratio": self._first_value(valuation, ["pb_ratio", "PBRatio"]),
            "ps_ratio": self._first_value(valuation, ["ps_ratio", "PSRatio"]),
            "pcf_ratio": self._first_value(valuation, ["pcf_ratio", "PCFRatio"]),
            "dividend_yield": self._first_value(valuation, ["dividend_yield", "DividendYield"]),
            "ev_to_ebitda": self._first_value(valuation, ["ev_to_ebitda", "EVToEBITDA"]),
            "ev_to_revenue": self._first_value(valuation, ["ev_to_revenue", "EVToRevenue"]),
            "revenue_ttm": self._metric(income, ["total_revenue", "TotalRevenue"]),
            "gross_profit_ttm": self._metric(income, ["gross_profit", "GrossProfit"]),
            "operating_income_ttm": self._metric(income, ["operating_income", "OperatingIncome"]),
            "net_income_ttm": self._metric(income, ["net_income", "NetIncome"]),
            "eps_ttm": self._metric(earning_reports, ["basic_eps", "BasicEPS"]),
            "roe": self._metric(operation, ["roe", "ROE"]),
            "roa": self._metric(operation, ["roa", "ROA"]),
            "debt_to_equity": self._metric(operation, ["debt_equity_ratio", "DebtEquityRatio"]),
            "current_ratio": self._metric(operation, ["current_ratio", "CurrentRatio"]),
            "quick_ratio": self._metric(operation, ["quick_ratio", "QuickRatio"]),
            "asset_turnover": self._metric(operation, ["assets_turnover", "AssetsTurnover"]),
            "gross_margin": self._metric(operation, ["gross_margin", "GrossMargin"]),
            "operating_margin": self._metric(operation, ["operating_margin", "OperatingMargin"]),
            "net_margin": self._metric(operation, ["net_margin", "NetMargin"]),
        }

    def _emit(self, prefix, rows):
        raw = "\n".join(rows).encode("utf-8")
        encoded = base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")
        n_chunks = max(1, -(-len(encoded) // self._CHUNK))
        self.set_runtime_statistic(f"{prefix}_N", str(n_chunks))
        for i in range(n_chunks):
            self.set_runtime_statistic(f"{prefix}_{i:04d}", encoded[i * self._CHUNK : (i + 1) * self._CHUNK])

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
    def _get_obj(obj, *names):
        if obj is None:
            return None
        for name in names:
            value = getattr(obj, name, None)
            if value is not None:
                return value
        return None

    @classmethod
    def _first_value(cls, obj, names):
        if obj is None:
            return ""
        for name in names:
            value = getattr(obj, name, None)
            if value is not None:
                return cls._clean_value(value)
        return ""

    @classmethod
    def _metric(cls, obj, names):
        metric = cls._first_value(obj, names)
        if metric in ("", None):
            return ""
        value = cls._first_value(metric, ["twelve_months", "TwelveMonths", "value", "Value"])
        return value if value not in ("", None) else metric

    @staticmethod
    def _clean_value(value):
        if value is None:
            return ""
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
