from abc import ABC, abstractmethod
from enum import IntEnum
import pandas as pd
from logger import logger

class Signal(IntEnum):
    SELL = -1
    HOLD = 0
    BUY = 1

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
            return Signal.BUY
        elif change1 < 0 and change2 < 0:
            return Signal.SELL
            
        return Signal.HOLD
    
class VWAPReversionStrategy(BaseStrategy):
    """Trade reversions to VWAP using Alpaca's built-in VWAP"""
    
    def __init__(self, parameters=None):
        super().__init__(parameters)
        self.lookback = parameters.get('lookback', 2)  # How many bars to look back for valid VWAP
        self.buy_threshold = parameters.get('buy_threshold', -0.0025)  # -0.8%
        self.sell_threshold = parameters.get('sell_threshold', 0.0025)  # +0.8%
        self.signals_generated = 0
        self.buy_signals = 0
        self.sell_signals = 0
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        if len(data) < 2:
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
        
        # Calculate distance from VWAP
        distance_pct = (current_price - vwap) / vwap
        logger.debug(f"VWAP DISTANCE: {distance_pct:.4f}")

        signal = Signal.HOLD
        
        # Buy when price is below VWAP by threshold (undervalued)
        if distance_pct < self.buy_threshold:
            signal = Signal.BUY
            self.buy_signals += 1
        
        # Sell when price is above VWAP by threshold (overvalued)
        elif distance_pct > self.sell_threshold:
            signal = Signal.SELL
            self.sell_signals += 1
        
        self.signals_generated += 1
        return signal