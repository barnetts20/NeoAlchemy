from abc import ABC, abstractmethod
from enum import IntEnum
import pandas as pd

class Signal(IntEnum):
    SELL = -1
    HOLD = 0
    BUY = 1

class BaseStrategy(ABC):
    """
    Blueprint for all trading logic.
    """
    def __init__(self, parameters: dict):
        self.params = parameters

    @abstractmethod
    def decide(self, data: pd.DataFrame) -> Signal:
        """
        Processes data and returns a decision: 'BUY', 'SELL', or 'HOLD'.
        """
        pass

class ConsecutiveChangeStrategy(BaseStrategy):
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        # We need at least 3 bars to detect 2 changes
        if len(data) < 3:
            return Signal.HOLD
            
        # Get the closing prices
        closes = data['close'].tail(3).values
        
        change1 = closes[1] - closes[0]
        change2 = closes[2] - closes[1]
        
        if change1 > 0 and change2 > 0:
            return Signal.BUY
        elif change1 < 0 and change2 < 0:
            return Signal.SELL
            
        return Signal.HOLD