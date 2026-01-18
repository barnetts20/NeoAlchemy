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
    def __init__(self, parameters: dict = None):
        self.params = parameters or {}

    @abstractmethod
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """Processes data and returns a Signal."""
        pass

class ConsecutiveChangeStrategy(BaseStrategy):
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        if len(data) < 3:
            return Signal.HOLD
            
        # tail(3) gives us the last 3 rows
        closes = data['close'].tail(3).values
        
        change1 = closes[1] - closes[0]
        change2 = closes[2] - closes[1]
        
        if change1 > 0 and change2 > 0:
            return Signal.OPEN_LONG
        elif change1 < 0 and change2 < 0:
            return Signal.CLOSE_LONG
            
        return Signal.HOLD
    
class VWAPReversionStrategy(BaseStrategy):
    """Trade reversions to VWAP using Alpaca's built-in VWAP.
    Uses banding approach with separate thresholds for opening and closing positions:
    - OPEN_LONG when price < open_long_threshold (e.g., -0.2% below VWAP)
    - CLOSE_LONG when price >= close_long_threshold (e.g., +0.15% above VWAP)
    - OPEN_SHORT when price > open_short_threshold (e.g., +0.2% above VWAP)
    - CLOSE_SHORT when price <= close_short_threshold (e.g., -0.15% below VWAP)
    
    This creates bands around VWAP for entry and exit points.
    """
    
    def __init__(self, parameters=None):
        super().__init__(parameters)
        self.lookback = parameters.get('lookback', 1)  # How many bars to look back for valid VWAP
        self.open_long_threshold = parameters.get('open_long_threshold', -0.002)
        self.close_long_threshold = parameters.get('close_long_threshold', 0.0015)
        self.open_short_threshold = parameters.get('open_short_threshold', 0.002)
        self.close_short_threshold = parameters.get('close_short_threshold', -0.0015)
        self.signals_generated = 0
        self.buy_signals = 0
        self.sell_signals = 0
        self.close_long_signals = 0
        self.close_short_signals = 0
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        if len(data) < 1:
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
        
        # Validate vwap is not zero to avoid division by zero
        if vwap == 0 or pd.isna(vwap):
            logger.warning("VWAP is zero or NaN, cannot calculate signal")
            return Signal.HOLD
        
        # Calculate distance from VWAP
        distance_pct = (current_price - vwap) / vwap
        logger.debug(f"VWAP DISTANCE: {distance_pct:.4f}")

        signal = Signal.HOLD
        
        # Check outermost thresholds first to prioritize extreme signals
        # OPEN_LONG: Price below open_long_threshold (e.g., -0.2% below VWAP) - outermost negative
        if distance_pct < self.open_long_threshold:
            signal = Signal.OPEN_LONG
            self.buy_signals += 1
        
        # OPEN_SHORT: Price above open_short_threshold (e.g., +0.2% above VWAP) - outermost positive
        elif distance_pct > self.open_short_threshold:
            signal = Signal.OPEN_SHORT
            self.sell_signals += 1
        
        # CLOSE_SHORT: Close short positions when price reaches close_short_threshold (e.g., -0.15% below VWAP)
        # Check this before CLOSE_LONG since it's further from VWAP (more negative)
        elif distance_pct <= self.close_short_threshold:
            signal = Signal.CLOSE_SHORT
            self.close_short_signals += 1
        
        # CLOSE_LONG: Close long positions when price reaches close_long_threshold (e.g., +0.15% above VWAP)
        elif distance_pct >= self.close_long_threshold:
            signal = Signal.CLOSE_LONG
            self.close_long_signals += 1
        
        self.signals_generated += 1
        return signal