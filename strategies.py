from abc import ABC, abstractmethod
from enum import IntEnum
import pandas as pd
from logger import logger

class Signal(IntEnum):
    CLOSE_SHORT = -2
    CLOSE_LONG  = -1
    HOLD        = 0
    OPEN_LONG   = 1
    OPEN_SHORT  = 2

class BaseStrategy(ABC):
    def __init__(self, window_size: int = 1, parameters: dict = None):
        self.params = parameters or {}
        self.window_size = window_size

    @abstractmethod
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """Processes data and returns a Signal."""
        pass

class ConsecutiveChangeStrategy(BaseStrategy):
    def __init__(self, parameters=None):
        params = parameters or {}
        super().__init__(3, params)

    def generate_signal(self, data: pd.DataFrame) -> Signal:
        if len(data) < self.window_size:
            return Signal.HOLD
            
        # tail(3) gives us the last 3 rows
        closes = data['close'].tail(self.window_size).values
        
        change1 = closes[1] - closes[0]
        change2 = closes[2] - closes[1]
        
        if change1 > 0 and change2 > 0:
            return Signal.OPEN_LONG
        elif change1 < 0 and change2 < 0:
            return Signal.CLOSE_LONG
            
        return Signal.HOLD
    
class VWAPReversionStrategy(BaseStrategy):
    """Trade reversions to VWAP using Alpaca's built-in VWAP.
    Uses banding approach with separate thresholds for opening and closing long positions:
    - OPEN_LONG when vwap distance < open_long_threshold
    - CLOSE_LONG when vwap distance >= close_long_threshold
    
    This creates bands around VWAP for entry and exit points.
    """
    
    def __init__(self, parameters=None):
        params = parameters or {}
        super().__init__(31, params)
        self.lookback = self.window_size
        self.open_long_threshold = parameters.get('open_long_threshold', -0.008)
        self.close_long_threshold = parameters.get('close_long_threshold', 0.004)
        self.signals_generated = 0
        self.buy_signals = 0
        self.sell_signals = 0
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        if len(data) < self.window_size:
            return Signal.HOLD
        
        # Validate required columns
        if 'close' not in data.columns:
            logger.warning("DataFrame missing 'close' column")
            return Signal.HOLD
        if 'vwap' not in data.columns:
            logger.warning("DataFrame missing 'vwap' column")
            return Signal.HOLD
        
        # Look at recent bars to find one with valid VWAP
        recent = data.tail(self.lookback) if len(data) >= self.lookback else data
        
        # Filter for bars with valid VWAP (not null, not zero)
        valid_bars = recent[recent['vwap'].notna() & (recent['vwap'] > 0)]
        
        if len(valid_bars) == 0:
            return Signal.HOLD
        
        # Use the most recent bar with valid VWAP
        latest = valid_bars.iloc[-1]
        current_price = latest['close']
        vwap = latest['vwap']

        # If VWAP is still 0 (shouldn't happen due to filtering, but safeguard)
        # or if it's somehow NaN, use current price as fallback
        if vwap == 0 or pd.isna(vwap) or vwap is None:
            logger.debug(f"VWAP is invalid ({vwap}), using current price as fallback")
            vwap = current_price
        
        # Calculate distance from VWAP
        distance_pct = (current_price - vwap) / vwap

        signal = Signal.HOLD
        
        # OPEN_LONG: Price below open_long_threshold
        if distance_pct < self.open_long_threshold:
            signal = Signal.OPEN_LONG
            self.buy_signals += 1
        
        # CLOSE_LONG: Close long positions when price reaches close_long_threshold
        elif distance_pct >= self.close_long_threshold:
            signal = Signal.CLOSE_LONG
            self.sell_signals += 1
        
        self.signals_generated += 1

        logger.debug(f"SIGNAL: {signal.name}, VWAP DISTANCE: {distance_pct:.4f}, OPEN THRESHOLD: {self.open_long_threshold}, CLOSE THRESHOLD: {self.close_long_threshold}")
        return signal
    
"""
MACD Strategy - Moving Average Convergence Divergence

Classic momentum strategy using MACD indicator for trend following.
"""

import pandas as pd
from strategies import BaseStrategy, Signal
from logger import logger


import pandas as pd
from strategies import BaseStrategy, Signal
from logger import logger


class MACDStrategy(BaseStrategy):
    """
    MACD Momentum Strategy
    
    Signals:
        OPEN_LONG:  MACD crosses above Signal line (bullish crossover)
        CLOSE_LONG: MACD crosses below Signal line (bearish crossover)
    
    Parameters:
        fast_period (int): Fast EMA period (default: 12)
        slow_period (int): Slow EMA period (default: 26)
        signal_period (int): Signal line EMA period (default: 9)
        min_histogram (float): Minimum histogram value to trigger signal (default: 0.0)
                               Useful to avoid whipsaw in ranging markets
    
    Example:
        strategy = MACDStrategy(parameters={
            'fast_period': 12,
            'slow_period': 26,
            'signal_period': 9,
            'min_histogram': 0.0001  # 0.01% minimum separation
        })
    """
    
    def __init__(self, parameters=None):
        params = parameters or {}
        
        # MACD parameters
        self.fast_period = params.get('fast_period', 12)
        self.slow_period = params.get('slow_period', 26)
        self.signal_period = params.get('signal_period', 9)
        self.min_histogram = params.get('min_histogram', 0.0)
        
        # Window size = max period + signal period for stability
        window_size = self.slow_period + self.signal_period
        
        super().__init__(window_size=window_size, parameters=params)
        
        # Track previous state PER SYMBOL for crossover detection
        self.prev_macd_by_symbol = {}
        self.prev_signal_by_symbol = {}
        
        # Statistics per symbol
        self.signals_generated = 0
        self.bullish_crossovers = 0
        self.bearish_crossovers = 0
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """
        Generate trading signal based on MACD crossovers
        
        Args:
            data: DataFrame with 'close' column (single symbol's data)
        
        Returns:
            Signal: OPEN_LONG, CLOSE_LONG, or HOLD
        """
        if len(data) < self.window_size:
            return Signal.HOLD
        
        # Validate required columns
        if 'close' not in data.columns:
            logger.warning("DataFrame missing 'close' column")
            return Signal.HOLD
        
        # Extract symbol from data (if available in index or column)
        # If not available, use a generic key (single symbol mode)
        symbol = self._get_symbol_from_data(data)
        
        # Calculate MACD components
        close_prices = data['close']
        
        # Fast and slow EMAs
        ema_fast = close_prices.ewm(span=self.fast_period, adjust=False).mean()
        ema_slow = close_prices.ewm(span=self.slow_period, adjust=False).mean()
        
        # MACD line
        macd_line = ema_fast - ema_slow
        
        # Signal line (EMA of MACD)
        signal_line = macd_line.ewm(span=self.signal_period, adjust=False).mean()
        
        # Histogram (difference)
        histogram = macd_line - signal_line
        
        # Get current values
        current_macd = macd_line.iloc[-1]
        current_signal = signal_line.iloc[-1]
        current_histogram = histogram.iloc[-1]
        
        # Get previous values for THIS SYMBOL
        prev_macd = self.prev_macd_by_symbol.get(symbol)
        prev_signal = self.prev_signal_by_symbol.get(symbol)
        
        # If we don't have previous values for this symbol yet, initialize
        if prev_macd is None or prev_signal is None:
            # Use second-to-last values if available
            if len(macd_line) >= 2:
                prev_macd = macd_line.iloc[-2]
                prev_signal = signal_line.iloc[-2]
            else:
                # Not enough data, store current and return HOLD
                self.prev_macd_by_symbol[symbol] = current_macd
                self.prev_signal_by_symbol[symbol] = current_signal
                return Signal.HOLD
        
        # Debug logging
        logger.debug(
            f"{symbol} | MACD: {current_macd:.6f} | Signal: {current_signal:.6f} | "
            f"Histogram: {current_histogram:.6f}"
        )
        
        signal = Signal.HOLD
        
        # Bullish crossover: MACD crosses above Signal
        if prev_macd <= prev_signal and current_macd > current_signal:
            # Optional: require minimum separation to avoid noise
            if abs(current_histogram) >= self.min_histogram:
                signal = Signal.OPEN_LONG
                self.bullish_crossovers += 1
                logger.debug(f"{symbol} | Bullish crossover detected (histogram: {current_histogram:.6f})")
        
        # Bearish crossover: MACD crosses below Signal
        elif prev_macd >= prev_signal and current_macd < current_signal:
            if abs(current_histogram) >= self.min_histogram:
                signal = Signal.CLOSE_LONG
                self.bearish_crossovers += 1
                logger.debug(f"{symbol} | Bearish crossover detected (histogram: {current_histogram:.6f})")
        
        # Update previous values for this symbol
        self.prev_macd_by_symbol[symbol] = current_macd
        self.prev_signal_by_symbol[symbol] = current_signal
        
        self.signals_generated += 1
        
        return signal
    
    def _get_symbol_from_data(self, data: pd.DataFrame) -> str:
        """
        Extract symbol identifier from DataFrame
        
        Tries multiple methods:
        1. 'symbol' column
        2. Index name (if named)
        3. Falls back to 'default'
        """
        # Check if there's a 'symbol' column
        if 'symbol' in data.columns and len(data) > 0:
            return data['symbol'].iloc[0]
        
        # Check if index has a name we can use
        if hasattr(data.index, 'name') and data.index.name:
            return str(data.index.name)
        
        # Fallback for single-symbol backtests
        return 'default'
    
    def get_statistics(self) -> dict:
        """Return strategy statistics"""
        return {
            'signals_generated': self.signals_generated,
            'bullish_crossovers': self.bullish_crossovers,
            'bearish_crossovers': self.bearish_crossovers,
            'parameters': {
                'fast_period': self.fast_period,
                'slow_period': self.slow_period,
                'signal_period': self.signal_period,
                'min_histogram': self.min_histogram
            }
        }


class MACDHistogramStrategy(BaseStrategy):
    """
    MACD Histogram Strategy - Alternative approach
    
    Uses histogram zero-crossings instead of MACD/Signal crossings.
    Often gives earlier signals.
    
    Signals:
        OPEN_LONG:  Histogram crosses above zero (momentum turning bullish)
        CLOSE_LONG: Histogram crosses below zero (momentum turning bearish)
    
    Parameters:
        fast_period (int): Fast EMA period (default: 12)
        slow_period (int): Slow EMA period (default: 26)
        signal_period (int): Signal line EMA period (default: 9)
        histogram_threshold (float): Threshold for zero crossing (default: 0.0)
    """
    
    def __init__(self, parameters=None):
        params = parameters or {}
        
        self.fast_period = params.get('fast_period', 12)
        self.slow_period = params.get('slow_period', 26)
        self.signal_period = params.get('signal_period', 9)
        self.histogram_threshold = params.get('histogram_threshold', 0.0)
        
        window_size = self.slow_period + self.signal_period
        
        super().__init__(window_size=window_size, parameters=params)
        
        # Track previous histogram PER SYMBOL
        self.prev_histogram_by_symbol = {}
        
        self.signals_generated = 0
        self.zero_crosses_up = 0
        self.zero_crosses_down = 0
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """Generate signal based on histogram zero crossings"""
        if len(data) < self.window_size:
            return Signal.HOLD
        
        if 'close' not in data.columns:
            return Signal.HOLD
        
        # Get symbol identifier
        symbol = self._get_symbol_from_data(data)
        
        # Calculate MACD components
        close_prices = data['close']
        ema_fast = close_prices.ewm(span=self.fast_period, adjust=False).mean()
        ema_slow = close_prices.ewm(span=self.slow_period, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.signal_period, adjust=False).mean()
        histogram = macd_line - signal_line
        
        current_hist = histogram.iloc[-1]
        
        # Get previous histogram for this symbol
        prev_hist = self.prev_histogram_by_symbol.get(symbol)
        
        if prev_hist is None:
            # Initialize with second-to-last value if available
            if len(histogram) >= 2:
                prev_hist = histogram.iloc[-2]
            else:
                self.prev_histogram_by_symbol[symbol] = current_hist
                return Signal.HOLD
        
        logger.debug(f"{symbol} | Histogram: {current_hist:.6f}")
        
        signal = Signal.HOLD
        
        # Crosses above zero (bullish)
        if prev_hist <= self.histogram_threshold and current_hist > self.histogram_threshold:
            signal = Signal.OPEN_LONG
            self.zero_crosses_up += 1
            logger.debug(f"{symbol} | Histogram crossed above zero")
        
        # Crosses below zero (bearish)
        elif prev_hist >= self.histogram_threshold and current_hist < self.histogram_threshold:
            signal = Signal.CLOSE_LONG
            self.zero_crosses_down += 1
            logger.debug(f"{symbol} | Histogram crossed below zero")
        
        # Update previous histogram for this symbol
        self.prev_histogram_by_symbol[symbol] = current_hist
        
        self.signals_generated += 1
        return signal
    
    def _get_symbol_from_data(self, data: pd.DataFrame) -> str:
        """Extract symbol identifier from DataFrame"""
        if 'symbol' in data.columns and len(data) > 0:
            return data['symbol'].iloc[0]
        if hasattr(data.index, 'name') and data.index.name:
            return str(data.index.name)
        return 'default'
    
    def get_statistics(self) -> dict:
        """Return strategy statistics"""
        return {
            'signals_generated': self.signals_generated,
            'zero_crosses_up': self.zero_crosses_up,
            'zero_crosses_down': self.zero_crosses_down,
            'parameters': {
                'fast_period': self.fast_period,
                'slow_period': self.slow_period,
                'signal_period': self.signal_period,
                'histogram_threshold': self.histogram_threshold
            }
        }
