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
        super().__init__(1, params)
        self.lookback = self.window_size
        self.open_long_threshold = parameters.get('open_long_threshold', -0.001)
        self.close_long_threshold = parameters.get('close_long_threshold', 0.001)
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
        
        # Validate vwap is not zero to avoid division by zero
        if vwap == 0 or pd.isna(vwap):
            logger.warning("VWAP is zero or NaN, cannot calculate signal")
            return Signal.HOLD
        
        # Calculate distance from VWAP
        distance_pct = (current_price - vwap) / vwap
        logger.debug(f"VWAP DISTANCE: {distance_pct:.4f}")

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
        return signal