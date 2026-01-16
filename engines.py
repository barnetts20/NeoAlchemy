# engines.py
import asyncio
import selectors
import sys
import pandas as pd
from datetime import datetime, timezone
from typing import List, Dict, Optional
from alpaca.data.models import Bar

from agents import ConsecutiveChangeAgent
from brokers import LocalSimBroker, LiveAlpacaBroker
from db_connection import get_conn
from strategies import ConsecutiveChangeStrategy
from psycopg import AsyncConnection
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


class LiveEngine:
    """
    Live trading engine that streams real-time data from Alpaca
    and executes trades through LiveAlpacaBroker
    """
    
    def __init__(
        self,
        broker: LiveAlpacaBroker,
        agent: ConsecutiveChangeAgent,
        symbols: List[str],
        asset_type: str = "crypto",  # "stock" or "crypto"
        window_size: int = 10,
    ):
        self.broker = broker
        self.agent = agent
        self.symbols = symbols
        self.asset_type = asset_type
        self.window_size = window_size
        
        # Get the appropriate stream from project_context (already initialized with credentials)
        if asset_type == "crypto":
            from project_context import CRYPTO_LIVE_DATA_STREAM
            self.stream = CRYPTO_LIVE_DATA_STREAM
        else:
            from project_context import STOCK_LIVE_DATA_STREAM
            self.stream = STOCK_LIVE_DATA_STREAM
        
        # Data buffer for each symbol - stores recent bars
        self.bar_data: Dict[str, pd.DataFrame] = {
            symbol: pd.DataFrame(columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
            for symbol in symbols
        }
        
        # Running state
        self.is_running = False
        self.last_evaluation = {}
        
    async def start(self):
        """Start the live trading system"""
        logger.info(f"Starting live engine ({self.asset_type}) with symbols: {self.symbols}")
        logger.info(f"Window size: {self.window_size}")
        
        # Subscribe to bars for all symbols
        self.stream.subscribe_bars(self._on_bar, *self.symbols)
        
        self.is_running = True
        
        # Log initial account status
        try:
            account = self.broker.get_account()
            logger.info(f"Account equity: ${float(account.get('equity', 0)):,.2f}")
            logger.info(f"Buying power: ${float(account.get('buying_power', 0)):,.2f}")
            logger.info(f"Cash: ${float(account.get('cash', 0)):,.2f}")
        except Exception as e:
            logger.warning(f"Could not fetch account info: {e}")
        
        # Start the stream
        try:
            logger.info("Starting data stream...")
            await self.stream._run_forever()
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        finally:
            await self.shutdown()
    
    async def _on_bar(self, bar: Bar):
        """
        Callback when new bar data is received
        
        Args:
            bar: Alpaca Bar object with fields: symbol, timestamp, open, high, low, close, volume
        """
        symbol = bar.symbol
        
        # Log the incoming bar (no emojis for Windows compatibility)
        logger.info(
            f"BAR RECEIVED - {symbol}: "
            f"close=${bar.close:.2f}, volume={bar.volume:.4f}, "
            f"time={bar.timestamp}"
        )
        
        # Convert bar to dataframe row
        new_row = pd.DataFrame([{
            'ts': bar.timestamp,
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': bar.volume
        }])
        
        # Append to buffer (fix for pandas FutureWarning)
        if self.bar_data[symbol].empty:
            self.bar_data[symbol] = new_row
        else:
            self.bar_data[symbol] = pd.concat([self.bar_data[symbol], new_row], ignore_index=True)
        
        # Keep only the data we need (window_size + some buffer)
        max_bars = self.window_size * 3  # Keep 3x window size for safety
        if len(self.bar_data[symbol]) > max_bars:
            self.bar_data[symbol] = self.bar_data[symbol].iloc[-max_bars:].reset_index(drop=True)
        
        logger.info(f"Buffer size for {symbol}: {len(self.bar_data[symbol])}/{self.window_size + 1} bars needed")
        
        # Check if we have enough data to evaluate
        if len(self.bar_data[symbol]) >= self.window_size:
            logger.info(f"EVALUATING strategy for {symbol}...")
            await self._evaluate_symbol(symbol)
        else:
            logger.info(f"WAITING for more data for {symbol}: {len(self.bar_data[symbol])}/{self.window_size + 1}")

    async def _evaluate_symbol(self, symbol: str):
        """Evaluate strategy for a specific symbol"""
        try:
            # Get the window of data (same as backtest)
            df = self.bar_data[symbol].set_index('ts')
            window = df.iloc[-(self.window_size + 1):]
            
            if len(window) < self.window_size + 1:
                logger.warning(f"Not enough data for {symbol}: {len(window)}/{self.window_size + 1}")
                return
            
            current_price = window['close'].iloc[-1]
            
            logger.info(f"AGENT processing tick for {symbol} at ${current_price:.2f}")
            
            # Agent processes the tick (same interface as backtest)
            self.agent.handle_tick(symbol, window, self.broker)
            
            logger.info(f"AGENT finished processing {symbol}")
            
            # Log account state periodically
            now = datetime.now(timezone.utc)
            last_log = self.last_evaluation.get(symbol, datetime.min.replace(tzinfo=timezone.utc))
            
            if (now - last_log).total_seconds() > 60:  # Log every minute
                try:
                    account = self.broker.get_account()
                    positions = self.broker.get_all_positions()
                    
                    logger.info("=" * 60)
                    logger.info(
                        f"PORTFOLIO [{symbol}] Price: ${current_price:.2f} | "
                        f"Equity: ${float(account.get('equity', 0)):,.2f} | "
                        f"Positions: {len(positions)}"
                    )
                    
                    if positions:
                        for pos in positions:
                            logger.info(
                                f"  POSITION {pos['symbol']}: {pos['qty']} @ ${pos['current_price']:.2f} "
                                f"(P&L: ${pos['unrealized_pl']:.2f})"
                            )
                    logger.info("=" * 60)
                    
                except Exception as e:
                    logger.warning(f"Could not fetch account info: {e}")
                
                self.last_evaluation[symbol] = now
                
        except Exception as e:
            logger.error(f"ERROR evaluating {symbol}: {e}", exc_info=True)
    
    async def shutdown(self):
        """Gracefully shutdown the engine"""
        logger.info("Shutting down live engine...")
        self.is_running = False
        
        # Close stream connections
        try:
            await self.stream.stop_ws()
            logger.info("Stream stopped")
        except Exception as e:
            logger.error(f"Error stopping stream: {e}")
        
        # Log final positions and account state
        try:
            account = self.broker.get_account()
            positions = self.broker.get_all_positions()
            
            logger.info("=" * 60)
            logger.info("FINAL ACCOUNT STATE")
            logger.info("=" * 60)
            logger.info(f"Equity: ${float(account.get('equity', 0)):,.2f}")
            logger.info(f"Cash: ${float(account.get('cash', 0)):,.2f}")
            logger.info(f"Buying Power: ${float(account.get('buying_power', 0)):,.2f}")
            logger.info(f"Open Positions: {len(positions)}")
            
            if positions:
                logger.info("\nPositions:")
                for pos in positions:
                    logger.info(
                        f"  {pos['symbol']}: {pos['qty']} shares @ "
                        f"${pos['current_price']:.2f} "
                        f"(P&L: ${pos['unrealized_pl']:.2f})"
                    )
            
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Error getting final state: {e}")
        
        logger.info("Shutdown complete")


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
                    row += f"{val:>12,.2f}"
                else:
                    row += f"{str(val):>12}"
            print(row)
        print("="*65)


async def run_live_trading(symbols: List[str], asset_type: str = "crypto"):
    """
    Run live paper trading with real-time data from Alpaca
    
    Args:
        symbols: List of symbols to trade
        asset_type: "stock" or "crypto"
    """
    logger.info(f"Initializing live trading for {asset_type}: {symbols}")
    
    # Initialize broker (uses credentials from project_context)
    broker = LiveAlpacaBroker()
    
    # Initialize strategy and agent (same as backtest)
    strategy = ConsecutiveChangeStrategy(parameters={})
    agent = ConsecutiveChangeAgent(strategy)
    
    # Create live engine (will use streams from project_context)
    engine = LiveEngine(
        broker=broker,
        agent=agent,
        symbols=symbols,
        asset_type=asset_type,
        window_size=3
    )
    
    # Start the engine
    await engine.start()


if __name__ == "__main__":
    # Standard cross-platform loop handling
    if sys.platform == "win32":
        loop_factory = lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
    else:
        loop_factory = None

    # Check command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "live":
        # Live trading mode
        asset_type = "crypto"  # Default to crypto
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD"]  # Default crypto symbols
        
        if len(sys.argv) > 2:
            if sys.argv[2] == "stock":
                asset_type = "stock"
                symbols = ["AAPL", "MSFT", "GOOGL"]
            else:
                symbols = sys.argv[2].split(",")
        
        try:
            asyncio.run(run_live_trading(symbols, asset_type), loop_factory=loop_factory)
        except KeyboardInterrupt:
            logger.info("Live trading terminated by user.")
    else:
        # Backtest mode (default)
        try:
            asyncio.run(run_standalone_backtest("crypto"), loop_factory=loop_factory)
        except KeyboardInterrupt:
            logger.info("Backtest process terminated by user.")