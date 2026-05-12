import logging
import threading

from utils.config import config

try:
    import futu as ft
except ImportError:
    ft = None

logger = logging.getLogger(__name__)


class MoomooConnectionError(RuntimeError):
    pass


class MoomooClient:
    """Thin Moomoo OpenD client for quote reads and paper-trading checks."""

    def __init__(self):
        if ft is None:
            raise MoomooConnectionError("futu-api is not installed")

        self.host = config.MOOMOO_HOST
        self.port = config.MOOMOO_PORT
        self.password = config.MOOMOO_PASSWORD or ""
        self.security_firm = ft.SecurityFirm.FUTUINC
        self._quote_ctx = None
        self._trade_ctx = None
        self._lock = threading.Lock()

    def quote_context(self):
        with self._lock:
            if self._quote_ctx is None:
                self._quote_ctx = ft.OpenQuoteContext(host=self.host, port=self.port)
            return self._quote_ctx

    def trade_context(self, unlock=False):
        with self._lock:
            if self._trade_ctx is None:
                self._trade_ctx = ft.OpenSecTradeContext(
                    host=self.host,
                    port=self.port,
                    filter_trdmarket=ft.TrdMarket.US,
                    security_firm=self.security_firm,
                )
                if unlock and self.password:
                    ret, msg = self._trade_ctx.unlock_trade(self.password)
                    if ret != ft.RET_OK:
                        self._trade_ctx.close()
                        self._trade_ctx = None
                        raise MoomooConnectionError(f"unlock_trade failed: {msg}")
            return self._trade_ctx

    def close(self):
        with self._lock:
            for attr in ("_quote_ctx", "_trade_ctx"):
                ctx = getattr(self, attr)
                if ctx is not None:
                    try:
                        ctx.close()
                    except Exception:
                        logger.debug("failed to close %s", attr, exc_info=True)
                    setattr(self, attr, None)

    def get_accounts(self):
        ctx = self.trade_context(unlock=False)
        ret, data = ctx.get_acc_list()
        if ret != ft.RET_OK:
            raise MoomooConnectionError(f"get_acc_list failed: {data}")
        return data

    def get_paper_account_id(self):
        data = self.get_accounts()
        if data.empty:
            return None

        trd_env = data.get("trd_env")
        acc_type = data.get("acc_type")
        if trd_env is None:
            return None

        mask = trd_env.astype(str).str.upper().isin({"SIMULATE", "PAPER"})
        if acc_type is not None:
            cash_mask = acc_type.astype(str).str.upper().eq("CASH")
            cash_paper = data[mask & cash_mask]
            if not cash_paper.empty:
                return int(cash_paper["acc_id"].iloc[0])

        paper = data[mask]
        if paper.empty:
            return None
        return int(paper["acc_id"].iloc[0])

    def check_paper_trading(self):
        account_id = self.get_paper_account_id()
        if account_id is None:
            return {
                "ok": False,
                "message": "No SIMULATE/PAPER account found in Moomoo OpenD account list.",
            }

        ctx = self.trade_context(unlock=True)
        ret, data = ctx.accinfo_query(trd_env=ft.TrdEnv.SIMULATE, acc_id=account_id)
        if ret != ft.RET_OK:
            return {
                "ok": False,
                "account_id": account_id,
                "message": f"paper accinfo_query failed: {data}",
            }

        return {
            "ok": True,
            "account_id": account_id,
            "rows": len(data),
            "columns": list(data.columns),
        }

    def resolve_us_option_contract(self, symbol: str, expiry: str, strike: float, option_type: str):
        """Resolve a US option contract through Moomoo's option chain API."""
        code = symbol.upper()
        if not code.startswith("US."):
            code = f"US.{code}"
        opt_type = str(option_type).upper()
        if opt_type not in {"CALL", "PUT"}:
            raise MoomooConnectionError(f"unsupported option_type: {option_type}")

        quote_ctx = self.quote_context()
        futu_option_type = ft.OptionType.CALL if opt_type == "CALL" else ft.OptionType.PUT
        ret, data = quote_ctx.get_option_chain(
            code,
            start=expiry,
            end=expiry,
            option_type=futu_option_type,
        )
        if ret != ft.RET_OK:
            raise MoomooConnectionError(f"get_option_chain failed: {data}")
        if data.empty:
            return None

        strike_float = float(strike)
        matches = data[
            (data["option_type"].astype(str).str.upper() == opt_type)
            & (data["strike_time"].astype(str) == expiry)
            & ((data["strike_price"].astype(float) - strike_float).abs() < 0.0001)
        ]
        if matches.empty:
            return None
        return matches.iloc[0].to_dict()

    def market_snapshot(self, codes: list[str]):
        """Return market snapshots for stock or option codes."""
        quote_ctx = self.quote_context()
        ret, data = quote_ctx.get_market_snapshot(codes)
        if ret != ft.RET_OK:
            raise MoomooConnectionError(f"get_market_snapshot failed: {data}")
        return data
