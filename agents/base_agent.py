from abc import ABC, abstractmethod
from strategies.base_strategy import BaseStrategy, Signal
import pandas as pd

class BaseAgent(ABC):
    def __init__(self, strategy: BaseStrategy, symbol: str):
        self.strategy = strategy
        self.symbol = symbol
        self.position = 0  # 0 for flat, 1 for long

    @abstractmethod
    def handle_tick(self, data: pd.DataFrame):
        """Called every heartbeat to process new market data."""
        pass

class ConsecutiveChangeAgent(BaseAgent):
    def handle_tick(self, data: pd.DataFrame):
        signal = self.strategy.generate_signal(data)
        
        if signal == Signal.BUY and self.position == 0:
            print(f"[{self.symbol}] ENUM Signal BUY. Entering Long.")
            self.position = 1
            # Actual Broker logic here
            
        elif signal == Signal.SELL and self.position == 1:
            print(f"[{self.symbol}] ENUM Signal SELL. Exiting position.")
            self.position = 0
            # Actual Broker logic here