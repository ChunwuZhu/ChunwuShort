import time
from dataclasses import dataclass

from broker.moomoo import MoomooClient, MoomooConnectionError, ft


PAPER_ENV = ft.TrdEnv.SIMULATE if ft is not None else None


@dataclass
class PaperOrderResult:
    ok: bool
    account_id: int | None = None
    order_id: str | None = None
    message: str = ""
    data: object | None = None


class MoomooPaperTrader:
    """Paper-trading wrapper around Moomoo OpenD.

    This class intentionally hard-codes TrdEnv.SIMULATE for all trading calls.
    """

    def __init__(self, client: MoomooClient | None = None):
        self.client = client or MoomooClient()
        self._account_id = None

    def close(self):
        self.client.close()

    def account_id(self) -> int:
        if self._account_id is None:
            account_id = self.client.get_paper_account_id()
            if account_id is None:
                raise MoomooConnectionError("No SIMULATE/PAPER account found")
            self._account_id = account_id
        return self._account_id

    def account_info(self):
        ctx = self.client.trade_context(unlock=True)
        ret, data = ctx.accinfo_query(trd_env=PAPER_ENV, acc_id=self.account_id())
        if ret != ft.RET_OK:
            raise MoomooConnectionError(f"paper accinfo_query failed: {data}")
        return data

    def positions(self, code: str | None = None):
        ctx = self.client.trade_context(unlock=True)
        kwargs = {"trd_env": PAPER_ENV, "acc_id": self.account_id()}
        if code:
            kwargs["code"] = self.normalize_us_code(code)
        ret, data = ctx.position_list_query(**kwargs)
        if ret != ft.RET_OK:
            raise MoomooConnectionError(f"paper position_list_query failed: {data}")
        return data

    def orders(self, order_id: str | None = None):
        ctx = self.client.trade_context(unlock=True)
        ret, data = ctx.order_list_query(trd_env=PAPER_ENV, acc_id=self.account_id())
        if ret != ft.RET_OK:
            raise MoomooConnectionError(f"paper order_list_query failed: {data}")
        if order_id and not data.empty and "order_id" in data.columns:
            return data[data["order_id"].astype(str) == str(order_id)]
        return data

    def buy_market(self, symbol: str, qty: int | float = 1, fill_outside_rth=False) -> PaperOrderResult:
        return self._place_stock_order(
            symbol=symbol,
            qty=qty,
            side=ft.TrdSide.BUY,
            order_type=ft.OrderType.MARKET,
            price=0,
            fill_outside_rth=fill_outside_rth,
        )

    def sell_market(self, symbol: str, qty: int | float = 1, fill_outside_rth=False) -> PaperOrderResult:
        return self._place_stock_order(
            symbol=symbol,
            qty=qty,
            side=ft.TrdSide.SELL,
            order_type=ft.OrderType.MARKET,
            price=0,
            fill_outside_rth=fill_outside_rth,
        )

    def buy_limit(self, symbol: str, qty: int | float, price: float, fill_outside_rth=False) -> PaperOrderResult:
        return self._place_stock_order(
            symbol=symbol,
            qty=qty,
            side=ft.TrdSide.BUY,
            order_type=ft.OrderType.NORMAL,
            price=price,
            fill_outside_rth=fill_outside_rth,
        )

    def wait_for_order(self, order_id: str, timeout_sec=10, poll_sec=1):
        deadline = time.monotonic() + timeout_sec
        latest = None
        while time.monotonic() < deadline:
            latest = self.orders(order_id)
            if not latest.empty:
                status = str(latest["order_status"].iloc[0]).upper()
                if status in {"FILLED_ALL", "CANCELLED_ALL", "FAILED", "DISABLED", "DELETED"}:
                    return latest
            time.sleep(poll_sec)
        return latest

    def _place_stock_order(self, symbol, qty, side, order_type, price=0, fill_outside_rth=False) -> PaperOrderResult:
        code = self.normalize_us_code(symbol)
        ctx = self.client.trade_context(unlock=True)
        ret, data = ctx.place_order(
            price=round(float(price), 2),
            qty=qty,
            code=code,
            trd_side=side,
            order_type=order_type,
            trd_env=PAPER_ENV,
            acc_id=self.account_id(),
            fill_outside_rth=fill_outside_rth,
        )
        if ret != ft.RET_OK:
            return PaperOrderResult(
                ok=False,
                account_id=self.account_id(),
                message=str(data),
                data=data,
            )

        order_id = None
        if not data.empty and "order_id" in data.columns:
            order_id = str(data["order_id"].iloc[0])
        return PaperOrderResult(
            ok=True,
            account_id=self.account_id(),
            order_id=order_id,
            message="submitted",
            data=data,
        )

    @staticmethod
    def normalize_us_code(symbol: str) -> str:
        symbol = str(symbol).strip().upper()
        if symbol.startswith("US."):
            return symbol
        return f"US.{symbol}"
