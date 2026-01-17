from abc import ABC, abstractmethod
from enum import IntEnum
import pandas as pd

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
    """Trade reversions to VWAP with distance threshold"""
    
    def __init__(self, parameters=None):
        super().__init__(parameters)
        self.period = parameters.get('period', 20)
        self.buy_threshold = parameters.get('buy_threshold', -0.008)  # -2%'
        self.sell_threshold = parameters.get('sell_threshold', 0.008)  # +2%
        self.signals_generated = 0
        self.buy_signals = 0
        self.sell_signals = 0
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        if len(data) < self.period:
            return Signal.HOLD
        
        recent = data.tail(self.period)
        
        # Calculate VWAP
        typical_price = (recent['high'] + recent['low'] + recent['close']) / 3
        total_volume = recent['volume'].sum()
        
        # Safety check: if no volume, can't calculate VWAP
        if total_volume == 0 or pd.isna(total_volume):
            return Signal.HOLD
        
        vwap = (typical_price * recent['volume']).sum() / total_volume
        
        # Safety check: invalid VWAP
        if pd.isna(vwap) or vwap == 0:
            return Signal.HOLD
        
        current_price = recent['close'].iloc[-1]
        distance_pct = (current_price - vwap) / vwap
        
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