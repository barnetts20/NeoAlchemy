from abc import ABC, abstractmethod
from typing import List
import pandas as pd
from datetime import datetime, timezone
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from alpaca.data.models import Bar
from strategies import BaseStrategy, Signal
from logger import logger, LogHelper

class BaseAgent(ABC):
    def __init__(self, strategy: BaseStrategy):
        self.strategy = strategy

    @abstractmethod
    async def _on_bar(self, bar: 'Bar'):
        """Handle incoming bar data for both live trading and backtesting."""
        pass

    @abstractmethod
    def handle_tick(self, symbol: str, data: pd.DataFrame, broker):
        """Standardized signature for both Backtesting and Live."""
        pass

    @property
    def window_size(self) -> int:
        """Delegate to strategy's window size"""
        return self.strategy.window_size


class CryptoAgent(BaseAgent):
    def __init__(self, strategy: BaseStrategy, commitment: float = 0.5):
        super().__init__(strategy)
        self.commitment = commitment  # Fraction of cash to use per trade (0.0 to 1.0)
        self.broker = None  # Will be set by engine
        self.symbols = []   # Will be set by engine
        self.stream = None  # Will be set by engine (for live trading)
        self.bar_data = {}  # For live trading bar buffering
        self.is_running = False

    def set_broker(self, broker):
        """Set the broker for this agent"""
        self.broker = broker

    def set_symbols(self, symbols: List[str]):
        """Set the symbols this agent should trade"""
        self.symbols = symbols
        # Initialize bar data buffer for each symbol (use lists for efficiency)
        self.bar_data = {symbol: [] for symbol in symbols}

    def set_stream(self, stream):
        """Set the data stream for live trading"""
        self.stream = stream

    async def start(self):
        """Start the agent - subscribe to data streams"""
        if not self.broker:
            raise ValueError("Broker not set for agent")
        if not self.symbols:
            raise ValueError("Symbols not set for agent")

        self.is_running = True
        logger.info(f"Starting CryptoAgent with symbols: {self.symbols}")

        if self.stream:
            # Live trading mode - subscribe to real-time bars
            logger.info("Subscribing to live data streams...")
            self.stream.subscribe_bars(self._on_bar, *self.symbols)
            await self.stream._run_forever()
        else:
            # Backtest mode - agent will receive bars from engine via handle_bar
            logger.info("Agent ready for backtest mode")

    def stop(self):
        """Stop the agent"""
        self.is_running = False
        logger.info("CryptoAgent stopped")

    async def _on_bar(self, bar):
        """Handle incoming bar data (Alpaca Bar objects for both live and backtest)."""
        symbol = bar.symbol

        # Log the incoming bar
        vwap_display = f"${bar.vwap:.6f}" if bar.vwap and bar.vwap > 0 else "N/A"
        logger.debug(
            f"BAR RECEIVED - {symbol}: "
            f"close=${bar.close:.2f}, volume={bar.volume:.8f}, "
            f"vwap={vwap_display}, "
            f"time={bar.timestamp}"
        )

        # Use efficient list-based buffering for backtest performance
        if symbol not in self.bar_data:
            self.bar_data[symbol] = []

        # Append bar data as dict for internal processing
        bar_dict = {
            'ts': bar.timestamp,
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': bar.volume,
            'vwap': bar.vwap
        }
        self.bar_data[symbol].append(bar_dict)

        # Keep only recent data (sliding window) - use efficient list slicing
        max_bars = self.window_size * 3
        if len(self.bar_data[symbol]) > max_bars:
            self.bar_data[symbol] = self.bar_data[symbol][-max_bars:]

        # Check if we have enough data to evaluate
        if len(self.bar_data[symbol]) >= self.window_size:
            logger.debug(f"EVALUATING strategy for {symbol}...")
            try:
                self._evaluate_symbol(symbol)
            except Exception as e:
                logger.error(f"ERROR evaluating {symbol}: {e}")
        else:
            logger.debug(f"WAITING for more data for {symbol}: {len(self.bar_data[symbol])}/{self.window_size}")

    def _evaluate_symbol(self, symbol: str, bar_window: pd.DataFrame = None):
        """Evaluate strategy for a specific symbol"""
        try:
            # Use provided bar_window (backtest) or construct from buffer (live)
            if bar_window is not None:
                # Backtest mode - use provided window
                data = bar_window
            else:
                # Live mode - construct window from buffer (convert list to DataFrame)
                if not self.bar_data[symbol]:
                    return
                data = pd.DataFrame(self.bar_data[symbol]).set_index('ts')

            if len(data) < self.window_size:
                logger.warning(f"Not enough data for {symbol}: {len(data)}/{self.window_size}")
                return

            # Use the last window_size bars for strategy evaluation
            window = data.iloc[-self.window_size:] if len(data) >= self.window_size else data

            # Get timestamp from the window data (always available)
            timestamp = window.index[-1]

            # Call the existing handle_tick method with timestamp
            self.handle_tick(symbol, window, self.broker, timestamp)

        except Exception as e:
            logger.error(f"ERROR evaluating {symbol}: {e}", exc_info=True)
    
    def handle_tick(self, symbol: str, data: pd.DataFrame, broker, timestamp=None):
        # 1. Get the Signal
        signal = self.strategy.generate_signal(data)

        # 2. Check current position and broker state
        try:
            current_pos = broker.get_open_position(symbol)
            qty_owned = float(current_pos.get("qty", 0) or 0)
        except Exception as e:
            # If position doesn't exist or error fetching, assume no position
            logger.debug(f"Could not get position for {symbol}: {e}")
            qty_owned = 0.0
        
        # 3. Get Account Cash for sizing
        try:
            acc = broker.get_account()
            cash_value = acc.get("cash", 0)
            available_cash = float(cash_value if cash_value is not None else 0)
        except Exception as e:
            logger.error(f"ERROR | {symbol} | Failed to get account info | reason: {str(e)}")
            return
        
        # Validate data has required columns
        if 'close' not in data.columns or len(data) == 0:
            logger.warning(f"Invalid data for {symbol}: missing 'close' column or empty dataframe")
            return
        
        current_price = float(data['close'].iloc[-1])



        # Safeguard against extremely small prices that would result in huge positions
        # For crypto, reasonable minimum price might be $0.000001 (1 millionth of a dollar)
        MIN_REASONABLE_PRICE = 1e-6
        if current_price < MIN_REASONABLE_PRICE:
            logger.warning(f"Price too low for {symbol}: ${current_price:.8f} - skipping to avoid huge position sizes")
            return
        
        # Validate commitment is reasonable
        if not 0 < self.commitment <= 1:
            logger.warning(f"Invalid commitment value: {self.commitment}, must be between 0 and 1")
            return

        # --- Logic: BUY Signal ---
        if signal == Signal.OPEN_LONG:
            if qty_owned > 0:
                logger.debug(f"{symbol} | OPEN_LONG signal ignored - already have position (qty: {qty_owned:.6f})")
            else:
                # Calculate position size
                buy_qty = (available_cash * self.commitment) / current_price

                if buy_qty > 0:
                    try:
                        # Submit order
                        order_response = broker.submit_order(
                            symbol=symbol,
                            qty=buy_qty,
                            side=OrderSide.BUY,
                            order_type=OrderType.MARKET,
                            time_in_force=TimeInForce.GTC,
                            current_price=current_price,
                            created_at=timestamp.isoformat() if timestamp else None
                        )
                        
                        # Extract fee from order response (default to 0 if extraction fails)
                        order_fee = self._extract_fee(order_response) or 0.0
                        
                        # Log OPEN (plain text, no color)
                        timestamp_str = f"[{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] " if timestamp else ""
                        logger.info(LogHelper.colorize(
                            f"{timestamp_str}💰 OPEN | {symbol} | BUY {buy_qty:.6f} @ ${current_price:,.8f} | "
                            f"value: ${buy_qty * current_price:,.2f} | fee: ${order_fee:.2f}", "PURPLE")
                        )
                        
                        # Log account status after opening position
                        self._log_account_status(broker)
                        
                    except Exception as e:
                        logger.error(f"ERROR | {symbol} | Failed to OPEN_LONG | reason: {str(e)}")

        # --- Logic: CLOSE LONG ---
        elif signal == Signal.CLOSE_LONG:
            if qty_owned <= 0:
                logger.debug(f"{symbol} | CLOSE_LONG signal ignored - no position to close")
            else:
                try:
                    # Get position data (we already have it from earlier)
                    entry_price = float(current_pos.get("avg_entry_price", 0) or 0)
                    
                    # Get position created time if available (for hold duration)
                    # Different brokers may have different field names
                    created_at = current_pos.get('created_at') or current_pos.get('submitted_at')
                    hold_duration = self._calculate_hold_duration(created_at, timestamp) if created_at else "unknown"
                    
                    # Submit order
                    order_response = broker.submit_order(
                        symbol=symbol,
                        qty=qty_owned,
                        side=OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        time_in_force=TimeInForce.GTC,
                        current_price=current_price
                    )
                    
                    # Extract fee from order response (default to 0 if extraction fails)
                    order_fee = self._extract_fee(order_response) or 0.0

                    # Calculate P&L including fees (net return)
                    entry_value = qty_owned * entry_price
                    exit_value = qty_owned * current_price
                    pnl_dollars = (exit_value - order_fee) - entry_value  # Subtract exit fee
                    pnl_percent = (pnl_dollars / entry_value * 100) if entry_value > 0 else 0.0
                    
                    # Determine color and emoji based on P&L
                    emoji, color = LogHelper.determine_pnl_color(pnl_dollars, pnl_percent)
                    
                    # Build log message (all values guaranteed to be numbers)
                    timestamp_str = f"[{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] " if timestamp else ""
                    log_msg = (
                        f"{timestamp_str}{emoji} CLOSE | {symbol} | SELL {qty_owned:.6f} @ ${current_price:,.8f} "
                        f"(entry: ${entry_price:,.2f}) | "
                        f"P&L: {LogHelper.format_pnl(pnl_dollars, pnl_percent)} | "
                        f"fee: ${order_fee:.2f} | held: {hold_duration}"
                    )
                    
                    # Log with color (ONLY CLOSE logs get colored)
                    logger.info(LogHelper.colorize(log_msg, color))
                    
                    # Log account status after closing position
                    self._log_account_status(broker)
                    
                except Exception as e:
                    logger.error(f"ERROR | {symbol} | Failed to CLOSE_LONG | reason: {str(e)}")
        
        # --- Logic: SHORT Signals (not supported for crypto) ---
        elif signal == Signal.OPEN_SHORT:
            logger.error(f"ERROR | {symbol} | OPEN_SHORT not supported for crypto trading")
        
        elif signal == Signal.CLOSE_SHORT:
            logger.error(f"ERROR | {symbol} | CLOSE_SHORT not supported for crypto trading")

        # --- HOLD Signal ---
        else:
            logger.debug(f"SIGNAL | {symbol} | HOLD")
    
    def _extract_fee(self, order_response: dict) -> float:
        """
        Extract fee from order response
        
        For LocalSimBroker: order_response['_sim_fee_cash']
        For LiveAlpacaBroker: Calculate from order details
        
        Args:
            order_response: Order response dict from broker
        
        Returns:
            Fee amount in dollars
        """
        # Handle None or missing response
        if not order_response:
            return 0.0
        
        # Try sim broker first
        fee = order_response.get('_sim_fee_cash', 0)
        
        if fee == 0:
            # For live broker, calculate from filled price and qty
            # This is an approximation - actual fees may vary
            try:
                filled_qty = order_response.get('filled_qty', 0)
                avg_price = order_response.get('filled_avg_price', 0)
                
                # Handle None values
                qty = float(filled_qty if filled_qty is not None else 0)
                price = float(avg_price if avg_price is not None else 0)
                
                notional = qty * price
                
                # Crypto: 0.6% overall fee (Alpaca tier 1)
                symbol = order_response.get('symbol', '')
                if '/' in symbol:  # Crypto
                    fee = notional * 0.006
            except (TypeError, ValueError):
                fee = 0.0
        
        return float(fee)
    
    def _calculate_hold_duration(self, created_at, current_timestamp) -> str:
        """
        Calculate how long a position was held based on position created timestamp
        
        Args:
            created_at: Position creation timestamp (string or datetime)
        
        Returns:
            Formatted duration string like "2.5h" or "45m"
        """
        if not created_at:
            return "unknown"
        
        try:
            # Handle both string and datetime inputs
            if isinstance(created_at, str):
                from dateutil import parser
                open_time = parser.parse(created_at)
            else:
                open_time = created_at
            
            # Ensure timezone aware
            if open_time.tzinfo is None:
                open_time = open_time.replace(tzinfo=timezone.utc)

            # Use the provided current timestamp (from the bar being processed)
            close_time = current_timestamp
            duration_seconds = (close_time - open_time).total_seconds()
            
            # Format as hours or minutes
            if duration_seconds >= 3600:  # 1 hour or more
                hours = duration_seconds / 3600
                return f"{hours:.1f}h"
            else:
                minutes = duration_seconds / 60
                return f"{minutes:.0f}m"
        except Exception:
            return "unknown"
    
    def _log_account_status(self, broker):
        """
        Log account status after position changes (plain text, no color)

        Args:
            broker: Broker instance
        """
        try:
            acc = broker.get_account()
            positions = broker.get_all_positions()
            
            # Safe extraction with None handling
            equity_val = acc.get('equity', 0)
            cash_val = acc.get('cash', 0)
            initial_val = acc.get('initial_capital', equity_val)
            
            equity = float(equity_val if equity_val is not None else 0)
            cash = float(cash_val if cash_val is not None else 0)
            initial_equity = float(initial_val if initial_val is not None else equity)
            
            # Calculate equity change percentage
            equity_change_pct = ((equity - initial_equity) / initial_equity * 100) if initial_equity > 0 else 0.0
            
            # Calculate total unrealized P&L (with None handling)
            open_pnl = sum(float(pos.get('unrealized_pl', 0) or 0) for pos in positions)
            
            # Log account status (plain text)
            logger.info(LogHelper.colorize(
                f"🏦 ACCOUNT | Equity: ${equity:,.2f} ({'+' if equity_change_pct >= 0 else ''}{equity_change_pct:.2f}%) | "
                f"Cash: ${cash:,.2f} | Positions: {len(positions)} | Open P&L: {'+' if open_pnl >= 0 else ''}${open_pnl:.2f}",
                'BLUE')
            )
            # Log each position indented under account status
            if positions:
                for pos in positions:
                    symbol = pos.get('symbol', 'UNKNOWN')
                    qty = float(pos.get('qty', 0) or 0)
                    current_price = float(pos.get('current_price', 0) or 0)
                    avg_entry = float(pos.get('avg_entry_price', 0) or 0)
                    unrealized_pl = float(pos.get('unrealized_pl', 0) or 0)
                    unrealized_plpc = float(pos.get('unrealized_plpc', 0) or 0) * 100  # Convert to percentage
                    
                    logger.debug(LogHelper.colorize(
                        f"    ↳ {symbol}: {qty:.6f} @ ${current_price:.8f} "
                        f"(entry: ${avg_entry:.2f}) | "
                        f"P&L: {'+' if unrealized_pl >= 0 else ''}${unrealized_pl:.2f} "
                        f"({'+' if unrealized_plpc >= 0 else ''}{unrealized_plpc:.2f}%)", 
                        'BLUE')
                    )
        except Exception as e:
            logger.warning(f"Could not log account status: {e}")