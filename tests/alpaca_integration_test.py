import time
from brokers import LiveAlpacaBroker, LocalSimBroker
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce

def test_connection():
    broker = LiveAlpacaBroker()
    try:
        acc = broker.get_account()
        print(f"Successfully connected! Paper Equity: {acc['equity']}")
        # Test fetching positions (even if empty)
        pos = broker.get_all_positions()
        print(f"Current positions count: {len(pos)}")
    except Exception as e:
        print(f"Connection failed: {e}")

def test_round_trip():
    # broker = LiveAlpacaBroker()
    broker = LocalSimBroker()
    # --- CONFIGURATION ---
    # We use very small amounts for testing
    test_assets = [
        {"symbol": "AAPL", "qty": 1, "type": "stock"},
        {"symbol": "BTC/USD", "qty": 0.1, "type": "crypto"}
    ]

    for asset in test_assets:
        print(f"\n--- Testing {asset['type'].upper()}: {asset['symbol']} ---")
        orderId = ''
        try:
            # 1. BUY
            print(f"Executing BUY for {asset['qty']} {asset['symbol']}...")
            buy_order = broker.submit_order(
                symbol=asset['symbol'],
                qty=asset['qty'],
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.GTC
            )
            orderId = buy_order['id']
            print(f"Buy Order Submitted: ID {buy_order['id']}")
        except Exception as e:
            print(f"ERROR testing {asset['symbol']}: {e}")
  
        # 2. WAIT FOR FILL
        # In paper, market orders are usually instant, but let's be safe.
        print("Waiting 5 seconds for order fill and position sync...")
        time.sleep(5)

        try:  
            # 3. VERIFY POSITION
            pos = broker.get_open_position(asset['symbol'])
            if float(pos['qty']) > 0:
                print(f"Position Confirmed: {pos['qty']} units @ {pos['avg_entry_price']}")
            else:
                print("Warning: Position not found yet. Check Alpaca dashboard.")

            # 4. SELL (Liquidate)
            print(f"Executing SELL to close {asset['symbol']}...")
            sell_order = broker.submit_order(
                symbol=asset['symbol'],
                qty=pos['qty'],
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.GTC
            )
            print(f"Sell Order Submitted: ID {sell_order['id']}")
        except Exception as e:
            print(f"ERROR SELLING {asset['symbol']}: {e}")
            print(f"CANCEL ORDER {asset['symbol']}")
            broker.cancel_order_by_id(orderId)

        # 5. WAIT FOR FILL
        # In paper, market orders are usually instant, but let's be safe.
        print("Waiting 5 seconds for order fill and position sync...")
        time.sleep(5)

        try:
            # 6. VERIFY POSITION
            pos = broker.get_open_position(asset['symbol'])
            print("Warning: Position not terminated, sell failed.")
        except Exception as e:
            print(f"Position terminated: {asset['symbol']}")

if __name__ == "__main__":
    test_connection()
    test_round_trip()