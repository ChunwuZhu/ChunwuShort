import logging
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from broker.moomoo_paper import MoomooPaperTrader


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    trader = MoomooPaperTrader()
    try:
        account_id = trader.account_id()
        data = trader.account_info()
    finally:
        trader.close()

    print(f"OK paper trading account_id={account_id} rows={len(data)}")
    print("columns=" + ",".join(data.columns))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
