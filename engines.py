# engines.py
import asyncio
import selectors
import sys
import pandas as pd
from datetime import datetime, timezone
from typing import List, Dict
from alpaca.data.models import Bar
from agents import BaseAgent, CryptoAgent
from brokers import LocalSimBroker, LiveAlpacaBroker
from db_connection import get_conn
from strategies import VWAPReversionStrategy
from psycopg import AsyncConnection
from logger import LogHelper, logger
import random
from datetime import datetime, timedelta

class BacktestEngine:
    def __init__(self, broker, agent: BaseAgent):
        self.broker = broker  # The LocalSimBroker instance
        self.agent = agent
        self.window_size = agent.window_size
        self.results = {}

    async def run_backtest(self, repo: 'BacktestDataRepository', symbols: List[str], start_date: datetime, end_date: datetime, timeframe: str = "1M", chunk_days: int = 31, reverse_time: bool = False):
        """
        Runs simplified backtest by processing data in time-sliced chunks.
        Mirrors live trading by feeding timestamp-organized bars to agent.

        Args:
            repo: BacktestDataRepository instance for data access
            symbols: List of symbols to backtest
            timeframe: Timeframe string (e.g., "1M")
            chunk_days: Number of days to process at once (memory management)
            reverse_time: If True, process chunks in reverse chronological order
        """

        chunk_size = timedelta(days=chunk_days)

        # Initialize results tracking
        self.results = {}

        # Step 1: Construct time window and determine sampling order
        if reverse_time:
            # Start from end, increment backwards
            current_date = end_date
            step_direction = -chunk_size
            logger.info("Running backtest in REVERSE time order")
        else:
            # Start from beginning, increment forwards
            current_date = start_date
            step_direction = chunk_size
            logger.info("Running backtest in FORWARD time order")

        chunk_num = 0
        while (not reverse_time and current_date < end_date) or (reverse_time and current_date > start_date):
            # Calculate chunk boundaries
            if reverse_time:
                chunk_start = max(current_date - chunk_size, start_date)
                chunk_end = current_date
            else:
                chunk_start = current_date
                chunk_end = min(current_date + chunk_size, end_date)

            chunk_num += 1
            logger.info(f"Processing chunk {chunk_num}: {chunk_start.date()} to {chunk_end.date()}")

            # Step 2: Load chunk data as {timestamp: [Bar objects]}
            try:
                bars_by_timestamp = await repo.load_chunk_data(symbols, timeframe, chunk_start, chunk_end, reverse_time)

                if not bars_by_timestamp:
                    logger.debug("No data in this chunk")
                else:
                    total_bars = sum(len(bars) for bars in bars_by_timestamp.values())
                    logger.info(f"Loaded chunk data ({total_bars} total bars across {len(bars_by_timestamp)} timestamps)")

                # Step 3: Process the chunk
                await self._process_chunk(bars_by_timestamp)

            except Exception as e:
                logger.warning(f"Failed to load chunk data: {e}")

            # Move to next chunk
            current_date += step_direction

        logger.info("Backtest completed")
        return self.results

    # Database loading moved to BacktestDataRepository for proper separation of concerns

    async def _process_chunk(self, bars_by_timestamp: Dict[datetime, List]):
        """Process a chunk by iterating through ordered timestamps and feeding randomized bars."""
        import random

        if not bars_by_timestamp:
            return

        # The dict keys are already in the correct order (sorted by database query)
        # Just iterate through them sequentially
        logger.debug(f"Processing chunk with {len(bars_by_timestamp)} timestamps")

        for timestamp, bars_at_time in bars_by_timestamp.items():
            if not bars_at_time:
                continue

            # Randomize order to simulate real-time bar arrival
            random.shuffle(bars_at_time)

            logger.debug(f"Processing {len(bars_at_time)} bars at {timestamp}")

            # Feed each bar to agent's _on_bar method (same as live trading!)
            for bar in bars_at_time:
                try:
                    await self.agent._on_bar(bar)
                except Exception as e:
                    logger.error(f"Error processing bar for {bar.symbol}: {e}")
                    continue

                # Record results after each bar (for P&L tracking)
                acc = self.broker.get_account()
                if bar.symbol not in self.results:
                    self.results[bar.symbol] = []

                self.results[bar.symbol].append({
                    "timestamp": timestamp,
                    "cash": float(acc["cash"]),
                    "equity": float(acc["equity"]),
                    "price": bar.close
                })

class LiveCryptoEngine:
    """
    Live trading engine that orchestrates live trading.
    Delegates all trading logic and data subscriptions to the agent.
    """

    def __init__(
        self,
        broker: LiveAlpacaBroker,
        agent: CryptoAgent,
        symbols: List[str],
        asset_type: str = "crypto"
    ):
        self.broker = broker
        self.agent = agent
        self.symbols = symbols
        self.asset_type = asset_type

        # Get the appropriate stream from project_context
        if asset_type == "crypto":
            from project_context import CRYPTO_LIVE_DATA_STREAM
            stream = CRYPTO_LIVE_DATA_STREAM
        else:
            from project_context import STOCK_LIVE_DATA_STREAM
            stream = STOCK_LIVE_DATA_STREAM

        # Configure the agent with broker, symbols, and stream
        agent.set_broker(broker)
        agent.set_symbols(symbols)
        agent.set_stream(stream)

    async def start(self):
        """Start the live trading system by starting the agent"""
        logger.info(f"Starting live engine ({self.asset_type}) with symbols: {self.symbols}")

        # Log initial account status
        try:
            account = self.broker.get_account()
            logger.info(f"🏦 Account equity: ${float(account.get('equity', 0)):,.2f}")
            logger.info(f"💰 Buying power: ${float(account.get('buying_power', 0)):,.2f}")
            logger.info(f"💵 Cash: ${float(account.get('cash', 0)):,.2f}")
        except Exception as e:
            logger.warning(f"Could not fetch account info: {e}")

        # Start the agent - it handles all subscriptions and trading logic
        try:
            await self.agent.start()
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Gracefully shutdown the engine"""
        logger.info("Shutting down live engine...")
        self.agent.stop()

        # Log final positions and account state
        try:
            account = self.broker.get_account()
            positions = self.broker.get_all_positions()

            logger.info("=" * 60)
            logger.info("FINAL ACCOUNT STATE")
            logger.info("=" * 60)
            logger.info(f"🏦 Equity: ${float(account.get('equity', 0)):,.2f}")
            logger.info(f"💵 Cash: ${float(account.get('cash', 0)):,.2f}")
            logger.info(f"💰 Buying Power: ${float(account.get('buying_power', 0)):,.2f}")
            logger.info(f"📊 Open Positions: {len(positions)}")

            if positions:
                logger.info("\nPositions:")
                for pos in positions:
                    logger.info(
                        f"  {pos['symbol']}: {pos['qty']} @ "
                        f"${float(pos['current_price']):.8f} "
                        f"(P&L: ${float(pos['unrealized_pl']):.2f})"
                    )

            logger.info("=" * 60)

            self.broker.close_all_positions(True)

        except Exception as e:
            logger.error(f"Error getting final state: {e}")

        logger.info("Shutdown complete")
    
    # All bar processing is now handled directly by the agent
    
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
    
    # Give tasks time to cleanup
    await asyncio.sleep(0.5)
    
    # Cancel any remaining tasks
    try:
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        
        # Wait for tasks to complete cancellation
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.debug(f"Task cleanup: {e}")
    
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
                    f"  {pos['symbol']}: {pos['qty']} @ "
                    f"${float(pos['current_price']):.2f} "
                    f"(P&L: ${float(pos['unrealized_pl']):.2f})"
                )
        
        logger.info("=" * 60)

        self.broker.close_all_positions(True)
        
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
        
    @staticmethod
    def _map_row_to_bar(row: tuple) -> Bar:
        """
        Convert database row to Alpaca Bar object
        
        Args:
            row: Database row tuple (symbol, ts, open, high, low, close, volume, vwap, trade_count)
        
        Returns:
            Bar: Alpaca-compatible Bar object
        """

        symbol, ts, open_price, high, low, close, volume, trade_count, vwap = row
        raw_data = {
            't': ts,                                        # timestamp
            'o': float(open_price),                         # open
            'h': float(high),                               # high
            'l': float(low),                                # low
            'c': float(close),                              # close
            'v': float(volume),                             # volume
            'vw': float(vwap) if vwap else None,            # vwap
            'n': int(trade_count) if trade_count else None,  # trade_count
        }
        # Create Alpaca Bar object directly from database row
        return Bar(symbol=symbol, raw_data=raw_data)

    async def load_chunk_data(self, symbols, timeframe, start_date, end_date, reverse_time=False):
        """Load data for all symbols in a chunk and return {timestamp: [Bar objects]}."""
        table = self.table_map["crypto"][timeframe]

        # Order by timestamp based on reverse_time flag
        order_direction = "DESC" if reverse_time else "ASC"

        query = f"""
            SELECT symbol, ts, open, high, low, close, volume, trade_count, vwap
            FROM {table}
            WHERE symbol = ANY(%s) AND ts >= %s AND ts < %s
            ORDER BY ts {order_direction};
        """
        async with self.conn.cursor() as cur:
            await cur.execute(query, (symbols, start_date, end_date))
            rows = await cur.fetchall()

        if not rows:
            return {}

        # Group bars by timestamp, creating Alpaca Bar objects
        bars_by_timestamp = {}
        for row in rows:
            # Create Alpaca Bar object directly from database row
            bar = self._map_row_to_bar(row)
            ts = bar.timestamp
            # Group bars by timestamp
            if ts not in bars_by_timestamp:
                bars_by_timestamp[ts] = []
            bars_by_timestamp[ts].append(bar)

        return bars_by_timestamp

    async def load_symbol_chunk(self, symbol: str, timeframe: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Load data for a specific symbol and date range chunk."""
        table = self.table_map["crypto"][timeframe]
        query = f"""
            SELECT symbol, ts, open, high, low, close, volume, trade_count, vwap
            FROM {table}
            WHERE symbol = %s AND ts >= %s AND ts < %s
            ORDER BY ts ASC;
        """
        async with self.conn.cursor() as cur:
            await cur.execute(query, (symbol, start_date, end_date))
            rows = await cur.fetchall()

            if not rows:
                return None

            df = pd.DataFrame(rows, columns=['symbol', 'ts', 'open', 'high', 'low', 'close', 'volume', 'trade_count', 'vwap'])
            df.set_index('ts', inplace=True)
            return df

    async def fetch_history(self, asset_type: str, symbol: str, timeframe: str) -> pd.DataFrame:
        table = self.table_map[asset_type][timeframe]

        query = f"""
            SELECT *
            FROM {table}
            WHERE symbol = %s
            ORDER BY ts ASC;
        """
        async with self.conn.cursor() as cur:
            await cur.execute(query, (symbol,))
            rows = await cur.fetchall()

            df = pd.DataFrame(rows, columns=['symbol', 'ts', 'open', 'high', 'low', 'close', 'volume', 'vwap'])
            df.set_index('ts', inplace=True)
            return df


async def run_standalone_backtest(reverse_time: bool = False, timeframes = ["1M"]):
    """
    Runs a memory-efficient backtest against the database.
    Processes data in time chunks to minimize memory usage while maintaining
    real-time simulation behavior with randomized symbol processing order.

    Args:
        reverse_time: If True, process timestamps in reverse chronological order
                     (future to past) to test for trend-following vs predictive strategies

    Usage:
        python engines.py                    # Normal forward time backtest
        python engines.py --reverse          # Reverse time backtest
        python engines.py -r                 # Reverse time backtest (short flag)
    """
    async with await get_conn() as conn:
        repo = BacktestDataRepository(conn)
        symbols = await repo.get_active_symbols("crypto")

        # Only support 1M timeframe for now (crypto-focused)
        matrix_results = {}

        for tf in timeframes:
            if(tf == "1M"):
                chunk_days = 10
            elif(tf == "5M"):
                chunk_days = 50
            elif(tf == "1H"):
                chunk_days = 500 
            elif(tf == "1D"):
                chunk_days = 5000
            else:
                logger.error("INVALID TIME FRAME");

            mode = "REVERSE TIME" if reverse_time else "FORWARD TIME"
            logger.info(f"Starting {mode} backtest for {len(symbols)} crypto symbols on {tf}")

            # Fresh broker and agent for this timeframe (shared across all symbols)
            broker = LocalSimBroker(initial_cash=10000.0)
            strategy = VWAPReversionStrategy(parameters={})
            agent = CryptoAgent(strategy)

            # Configure agent for backtest mode (no stream)
            agent.set_broker(broker)
            agent.set_symbols(symbols)
            agent.is_running = True  # Enable backtest mode

            engine = BacktestEngine(broker, agent)

            try:
                # Run memory-efficient real-time simulation

                start_date = datetime(2024, 1, 1) # TODO: Should be passed in
                end_date = datetime.now() # TODO: Should be passed in with a default
                await engine.run_backtest(repo, symbols, start_date, end_date, tf, chunk_days, reverse_time=reverse_time)

                # Log signal summary
                hold_count = strategy.signals_generated - strategy.buy_signals - strategy.sell_signals
                logger.info(
                    f"Backtest {tf} - Total signals: {strategy.signals_generated}, "
                    f"OPEN_LONG: {strategy.buy_signals}, CLOSE_LONG: {strategy.sell_signals}, "
                    f"HOLD: {hold_count}"
                )

            except Exception as e:
                logger.error(f"Failed backtest for {tf}: {e}")
                for symbol in symbols:
                    matrix_results.setdefault(symbol, {})[tf] = "ERROR"

async def run_live_crypto_trading(symbols: List[str], asset_type: str = "crypto"):
    """
    Run live paper trading with real-time data from Alpaca
    
    Args:
        symbols: List of symbols to trade
        asset_type: "stock" or "crypto"
    """
    
    # Initialize broker (uses credentials from project_context)
    broker = LiveAlpacaBroker()
    
    # Initialize strategy and agent (same as backtest)
    strategy = VWAPReversionStrategy(parameters={})
    agent = CryptoAgent(strategy)
    
    # Create live engine (will use streams from project_context)
    engine = LiveCryptoEngine(
        broker=broker,
        agent=agent,
        symbols=symbols,
        asset_type=asset_type
    )
    
    # Start the engine
    await engine.start()


if __name__ == "__main__":
    # Standard cross-platform loop handling for Windows
    if sys.platform == "win32":
        # Windows requires SelectorEventLoop for psycopg compatibility
        loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        asyncio.set_event_loop(loop)
    else:
        loop = None

    # Check command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "live":
        # Live trading mode
        asset_type = "crypto"  # Default to crypto
        symbols = ["AAVE/USD", "AVAX/USD", "BAT/USD", "BCH/USD", "BTC/USD", "CRV/USD", "DOGE/USD", "DOT/USD", "ETH/USD", "GRT/USD", "LINK/USD", "LTC/USD", "PEPE/USD", "SHIB/USD", "SKY/USD", "SOL/USD", "SUSHI/USD", "UNI/USD", "XRP/USD", "XTZ/USD", "YFI/USD"]  # Available symbols
        
        try:
            if loop:
                loop.run_until_complete(run_live_crypto_trading(symbols, asset_type))
            else:
                asyncio.run(run_live_crypto_trading(symbols, asset_type))
        except KeyboardInterrupt:
            logger.info("Live trading terminated by user.")
        finally:
            if loop:
                # Cancel all tasks
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                # Run loop briefly to allow cancellation
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.close()
    else:
        # Backtest mode (default)
        # Check for reverse_time flag
        reverse_time = "--reverse" in sys.argv or "-r" in sys.argv

        if reverse_time:
            logger.info("Running backtest in REVERSE time order (future → past) to test for trend-following")

        try:
            if loop:
                loop.run_until_complete(run_standalone_backtest(reverse_time=reverse_time))
            else:
                asyncio.run(run_standalone_backtest(reverse_time=reverse_time))
        except KeyboardInterrupt:
            logger.info("Backtest process terminated by user.")
        finally:
            if loop:
                loop.close()