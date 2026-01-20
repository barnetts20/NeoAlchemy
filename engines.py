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


class BacktestEngine:
    def __init__(self, broker, agent: BaseAgent):
        self.broker = broker  # The LocalSimBroker instance
        self.agent = agent
        self.window_size = agent.window_size
        self.results = {}

    # Old per-symbol backtest method removed - using chunked approach instead

    async def run_backtest(self, repo: 'BacktestDataRepository', symbols: List[str], timeframe: str, chunk_days: int = 31, reverse_time: bool = False):
        """
        Runs memory-efficient backtest by processing data in time chunks.
        More closely mirrors live trading behavior with randomized symbol processing.

        Args:
            repo: BacktestDataRepository instance for data access
            symbols: List of symbols to backtest
            timeframe: Timeframe string (e.g., "1M")
            chunk_days: Number of days to process at once (memory management)
            reverse_time: If True, process timestamps in reverse chronological order
                         (future to past) to test for trend-following vs predictive strategies
        """
        import random
        from datetime import datetime, timedelta

        # For simplicity, let's process from a reasonable start date
        # In production, you'd want to query min/max dates more efficiently
        start_date = datetime(2024, 1, 1)  # Conservative start
        end_date = datetime.now()

        current_date = start_date
        chunk_size = timedelta(days=chunk_days)

        # Initialize results tracking
        self.results = {}

        while current_date < end_date:
            chunk_end = min(current_date + chunk_size, end_date)

            logger.info(f"Processing chunk: {current_date.date()} to {chunk_end.date()}")

            # Load data for this chunk only
            chunk_data = {}
            active_symbols = []

            for symbol in symbols:
                try:
                    # Load only data for this date range
                    df = await self._load_symbol_chunk(repo, symbol, timeframe, current_date, chunk_end)
                    if df is not None and len(df) >= self.window_size:
                        chunk_data[symbol] = df
                        active_symbols.append(symbol)
                        logger.debug(f"Loaded {len(df)} bars for {symbol} in chunk")
                except Exception as e:
                    logger.debug(f"Skipping {symbol} in chunk: {e}")

            if not active_symbols:
                logger.debug("No active symbols in this chunk, skipping")
                current_date = chunk_end
                continue

            # Process this chunk timestamp by timestamp
            await self._process_chunk_timestamps(chunk_data, active_symbols, reverse_time)

            current_date = chunk_end

        logger.info("Real-time backtest completed")
        return self.results

    async def _load_symbol_chunk(self, repo: 'BacktestDataRepository', symbol: str, timeframe: str,
                                start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Load data for a specific symbol and date range chunk."""
        async with await get_conn() as conn:
            table = repo.table_map["crypto"][timeframe]
            query = f"""
                SELECT ts, open, high, low, close, volume, vwap
                FROM {table}
                WHERE symbol = %s AND ts >= %s AND ts < %s
                ORDER BY ts ASC;
            """
            async with conn.cursor() as cur:
                await cur.execute(query, (symbol, start_date, end_date))
                rows = await cur.fetchall()

                if not rows:
                    return None

                df = pd.DataFrame(rows, columns=['ts', 'open', 'high', 'low', 'close', 'volume', 'vwap'])
                df.set_index('ts', inplace=True)
                return df

    async def _process_chunk_timestamps(self, chunk_data: Dict[str, pd.DataFrame], symbols: List[str], reverse_time: bool = False):
        """Process all timestamps in a data chunk."""
        import random

        # Get all unique timestamps in this chunk
        all_timestamps = set()
        for df in chunk_data.values():
            all_timestamps.update(df.index)

        # Sort timestamps based on reverse_time flag
        if reverse_time:
            sorted_timestamps = sorted(all_timestamps, reverse=True)  # Future to past
            logger.debug(f"Processing chunk in REVERSE time order: {len(sorted_timestamps)} timestamps")
        else:
            sorted_timestamps = sorted(all_timestamps)  # Past to future (normal)

        for timestamp in sorted_timestamps:
            # Find symbols that have data for this timestamp
            symbols_at_time = []
            for symbol in symbols:
                if symbol in chunk_data and timestamp in chunk_data[symbol].index:
                    symbols_at_time.append(symbol)

            if not symbols_at_time:
                continue

            # Randomize order to simulate real-time bar arrival
            random.shuffle(symbols_at_time)

            logger.debug(f"Processing {len(symbols_at_time)} symbols at {timestamp}")

            # Create synthetic Alpaca bars for each symbol at this timestamp
            bars_at_time = []
            for symbol in symbols_at_time:
                df = chunk_data[symbol]
                idx = df.index.get_loc(timestamp)

                # Ensure we have enough history for the window (skip if not)
                if idx < self.window_size - 1:
                    continue

                # Get the current bar data (latest candle in window)
                current_bar = df.iloc[idx]

                # VALIDATE PRICE DATA
                if current_bar['close'] <= 0:
                    logger.warning(f"Invalid price at {timestamp}: {current_bar['close']}. Skipping {symbol}.")
                    continue

                # Check for unrealistic price jumps (from previous bar)
                if idx > 0:
                    prev_bar = df.iloc[idx-1]
                    if prev_bar['close'] > 0:
                        change_pct = abs((current_bar['close'] - prev_bar['close']) / prev_bar['close'])
                        if change_pct > 5.0:  # 500% movement in one bar
                            logger.warning(
                                f"Extreme price movement at {timestamp}: "
                                f"{change_pct:.1%} from ${prev_bar['close']:.9f} to ${current_bar['close']:.9f}. "
                                f"Skipping {symbol}."
                            )
                            continue

                # Create synthetic Bar-like object (mimics Alpaca Bar interface)
                class MockBar:
                    def __init__(self, symbol, timestamp, open_, high, low, close, volume, vwap):
                        self.symbol = symbol
                        self.timestamp = timestamp
                        self.open = open_
                        self.high = high
                        self.low = low
                        self.close = close
                        self.volume = volume
                        self.vwap = vwap

                # Handle VWAP properly - use close price only if VWAP is missing/NaN
                # Don't override legitimate zero VWAP (which can happen with very low volume)
                vwap_value = current_bar.get('vwap')
                if vwap_value is None or pd.isna(vwap_value):
                    vwap_value = current_bar['close']  # Use close price as fallback for missing data

                synthetic_bar = MockBar(
                    symbol=symbol,
                    timestamp=timestamp,
                    open_=current_bar['open'],
                    high=current_bar['high'],
                    low=current_bar['low'],
                    close=current_bar['close'],
                    volume=current_bar['volume'],
                    vwap=vwap_value
                )

                bars_at_time.append(synthetic_bar)

            # Randomize bar order and feed to agent (EXACT same path as live trading)
            random.shuffle(bars_at_time)

            for bar in bars_at_time:
                logger.debug(LogHelper.colorize(
                    f"BACKTEST BAR - {bar.symbol}: "
                    f"close=${bar.close:.9f}, volume={bar.volume:.9f}, "
                    f"vwap=${bar.vwap:.9f}, "
                    f"time={bar.timestamp}",
                    'GREY')
                )

                # Call agent's _on_bar method - EXACT same path as live trading!
                await self.agent._on_bar(bar)

                # Record results after each bar (for P&L tracking)
                acc = self.broker.get_account()
                symbol = bar.symbol
                if symbol not in self.results:
                    self.results[symbol] = []

                self.results[symbol].append({
                    "timestamp": bar.timestamp,
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

    async def fetch_history(self, asset_type: str, symbol: str, timeframe: str) -> pd.DataFrame:
        table = self.table_map[asset_type][timeframe]
        query = f"""
            SELECT ts, open, high, low, close, volume, vwap 
            FROM {table} 
            WHERE symbol = %s 
            ORDER BY ts ASC;
        """
        async with self.conn.cursor() as cur:
            await cur.execute(query, (symbol,))
            rows = await cur.fetchall()
            
            df = pd.DataFrame(rows, columns=['ts', 'open', 'high', 'low', 'close', 'volume', 'vwap'])
            df.set_index('ts', inplace=True)
            return df


async def run_standalone_backtest(reverse_time: bool = False):
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
        timeframes = ["1M"]
        matrix_results = {}

        for tf in timeframes:
            window = 31
            if(tf == "5M"):
                window *= 5
            elif(tf == "1H"):
                window *= 60
            elif(tf == "1D"):
                window *= 60 * 24

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
                # Run memory-efficient real-time simulation (7-day chunks)
                await engine.run_backtest(repo, symbols, tf, window, reverse_time=reverse_time)

                # Process results for each symbol
                for symbol in symbols:
                    if symbol in engine.results and engine.results[symbol]:
                        # Convert list of dicts to DataFrame and get final equity
                        df_results = pd.DataFrame(engine.results[symbol]).set_index('timestamp')
                        if not df_results.empty:
                            final_equity = df_results['equity'].iloc[-1]
                            matrix_results[symbol] = {tf: round(final_equity, 2)}
                        else:
                            matrix_results[symbol] = {tf: "NO_DATA"}
                    else:
                        matrix_results[symbol] = {tf: "NO_DATA"}

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

        # --- Report Rendering ---
        print("\n" + "="*65)
        print("BEYOND-ALGO CRYPTO BACKTEST MATRIX")
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