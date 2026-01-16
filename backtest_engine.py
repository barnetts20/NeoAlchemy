import asyncio
import selectors
import sys
import pandas as pd

from agents import ConsecutiveChangeAgent
from brokers import LocalSimBroker
from db_connection import get_conn
from strategies import ConsecutiveChangeStrategy
from psycopg import AsyncConnection
from typing import List
from logger import logger

class BacktestEngine:
    def __init__(self, broker, agent, window_size=10):
        self.broker = broker  # The LocalSimBroker instance
        self.agent = agent    # The ConsecutiveChangeAgent instance
        self.window_size = window_size
        self.results = {}

    def run_backtest(self, symbol: str, df: pd.DataFrame):
        """Runs the strategy against a single symbol's dataframe."""
        history = []
        
        # Iterative Simulation (The Time Machine)
        for i in range(self.window_size, len(df)):
            # slice of data: 'window' represents what the agent 'knows' at this moment
            window = df.iloc[i - self.window_size : i + 1]
            current_price = window['close'].iloc[-1]
            timestamp = df.index[i]

            # 1. Update Broker's internal tape for current equity/fill calcs
            self.broker.update_price(symbol, current_price)

            # 2. Agent processes the tick (Passing symbol-agnostically)
            self.agent.handle_tick(symbol, window, self.broker)

            # 3. Capture state for analytics
            acc = self.broker.get_account()
            history.append({
                "timestamp": timestamp,
                "cash": float(acc["cash"]),
                "equity": float(acc["equity"]),
                "price": current_price
            })
            
        self.results[symbol] = pd.DataFrame(history).set_index("timestamp")
        return self.results[symbol]

class BacktestDataRepository:
    def __init__(self, conn: AsyncConnection):
        self.conn = conn
        # Reusing your table mapping logic
        self.table_map = {
            "stock": {"1D": "stock_candles_1d", "1H": "stock_candles_1h", "1M": "stock_candles_1m", "5M": "stock_candles_5m"},
            "crypto": {"1D": "crypto_candles_1d", "1H": "crypto_candles_1h", "1M": "crypto_candles_1m", "5M": "crypto_candles_5m"}
        }

    async def get_active_symbols(self, asset_type: str) -> List[str]:
        async with self.conn.cursor() as cur:
            await cur.execute("SELECT symbol FROM assets WHERE asset_type=%s AND active=TRUE;", (asset_type,))
            rows = await cur.fetchall()
            return [row[0] for row in rows]

    async def fetch_history(self, asset_type: str, symbol: str, timeframe: str) -> pd.DataFrame:
        table = self.table_map[asset_type][timeframe]
        query = f"""
            SELECT ts, open, high, low, close, volume 
            FROM {table} 
            WHERE symbol = %s 
            ORDER BY ts ASC;
        """
        async with self.conn.cursor() as cur:
            await cur.execute(query, (symbol,))
            rows = await cur.fetchall()
            
            df = pd.DataFrame(rows, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
            df.set_index('ts', inplace=True)
            return df
        
async def run_standalone_backtest(asset_type="crypto"):
    """
    Runs a full matrix backtest against the database.
    Resets the broker for every symbol/timeframe combination.
    """
    async with await get_conn() as conn:
        repo = BacktestDataRepository(conn)
        symbols = await repo.get_active_symbols(asset_type)
        
        # Match these exactly to your table_map keys
        timeframes = ["1D"]
        
        # results[symbol][timeframe] = final_equity
        matrix_results = {}

        for symbol in symbols:
            matrix_results[symbol] = {}
            for tf in timeframes:
                # 1. Fresh Start for every cell in the matrix
                broker = LocalSimBroker(initial_cash=10000.0)
                strategy = ConsecutiveChangeStrategy(parameters={})
                agent = ConsecutiveChangeAgent(strategy) 
                engine = BacktestEngine(broker, agent)

                try:
                    # 2. Fetch from DB (e.g., crypto_candles_1h)
                    df = await repo.fetch_history(asset_type, symbol, tf)
                    
                    if df is None or len(df) <= engine.window_size:
                        matrix_results[symbol][tf] = "NO_DATA"
                        continue

                    # 3. Run Simulation
                    logger.info(f"Simulating {symbol} on {tf} ({len(df)} bars)...")
                    engine.run_backtest(symbol, df)
                    
                    # 4. Extract Result
                    final_equity = engine.results[symbol]['equity'].iloc[-1]
                    matrix_results[symbol][tf] = round(final_equity, 2)
                    
                except Exception as e:
                    logger.error(f"Failed {symbol} @ {tf}: {e}")
                    matrix_results[symbol][tf] = "ERROR"

        # --- Report Rendering ---
        print("\n" + "="*65)
        print(f"BEYOND-ALGO BACKTEST MATRIX: {asset_type.upper()}")
        print("="*65)
        
        # Header Row
        header = f"{'Symbol':<15}" + "".join([f"{tf:>12}" for tf in timeframes])
        print(header)
        print("-" * len(header))
        
        # Data Rows
        for symbol, tfs in matrix_results.items():
            row = f"{symbol:<15}"
            for tf in timeframes:
                val = tfs.get(tf, "N/A")
                if isinstance(val, float):
                    # Color coding logic (optional): if val > 100k, it's green in your mind
                    row += f"{val:>12,.2f}"
                else:
                    row += f"{str(val):>12}"
            print(row)
        print("="*65)

if __name__ == "__main__":
    # Standard cross-platform loop handling
    if sys.platform == "win32":
        loop_factory = lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
    else:
        loop_factory = None

    try:
        # Run for Crypto by default
        asyncio.run(run_standalone_backtest("crypto"), loop_factory=loop_factory)
    except KeyboardInterrupt:
        logger.info("Backtest process terminated by user.")