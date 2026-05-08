import argparse
import logging
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from broker.moomoo_paper import MoomooPaperTrader


def main():
    parser = argparse.ArgumentParser(description="Moomoo paper-trading helper.")
    sub = parser.add_subparsers(dest="command", required=True)

    buy_market = sub.add_parser("buy-market")
    buy_market.add_argument("symbol")
    buy_market.add_argument("--qty", type=float, default=1)
    buy_market.add_argument("--wait", type=int, default=0)

    sell_market = sub.add_parser("sell-market")
    sell_market.add_argument("symbol")
    sell_market.add_argument("--qty", type=float, default=1)
    sell_market.add_argument("--wait", type=int, default=0)

    positions = sub.add_parser("positions")
    positions.add_argument("symbol", nargs="?")

    orders = sub.add_parser("orders")
    orders.add_argument("--order-id")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    trader = MoomooPaperTrader()
    try:
        if args.command == "buy-market":
            result = trader.buy_market(args.symbol, qty=args.qty)
            print_result(result, trader, args.wait)
        elif args.command == "sell-market":
            result = trader.sell_market(args.symbol, qty=args.qty)
            print_result(result, trader, args.wait)
        elif args.command == "positions":
            data = trader.positions(args.symbol)
            print(data.to_string(index=False) if not data.empty else "none")
        elif args.command == "orders":
            data = trader.orders(args.order_id)
            print(data.to_string(index=False) if not data.empty else "none")
    finally:
        trader.close()


def print_result(result, trader, wait):
    print(f"ok={result.ok} account_id={result.account_id} order_id={result.order_id} message={result.message}")
    if result.data is not None:
        print(result.data.to_string(index=False) if not result.data.empty else "empty")
    if result.ok and result.order_id and wait > 0:
        status = trader.wait_for_order(result.order_id, timeout_sec=wait)
        print("ORDER_STATUS")
        print(status.to_string(index=False) if status is not None and not status.empty else "none")


if __name__ == "__main__":
    raise SystemExit(main())
