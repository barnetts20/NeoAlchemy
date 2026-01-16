from abc import ABC, abstractmethod
import pandas as pd
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from strategies import BaseStrategy, Signal

class BaseAgent(ABC):
    def __init__(self, strategy: BaseStrategy):
        self.strategy = strategy

    @abstractmethod
    def handle_tick(self, symbol: str, data: pd.DataFrame, broker):
        """Standardized signature for both Backtesting and Live."""
        pass

class ConsecutiveChangeAgent(BaseAgent):
    def handle_tick(self, symbol: str, data: pd.DataFrame, broker):
        # 1. Get the Signal
        signal = self.strategy.generate_signal(data)
        
        # 2. Check current position and broker state
        current_pos = broker.get_open_position(symbol)
        qty_owned = float(current_pos.get("qty", 0))
        
        # 3. Get Account Cash for sizing
        acc = broker.get_account()
        available_cash = float(acc["cash"])
        
        current_price = float(data['close'].iloc[-1])

        # --- Logic: BUY (All-In) ---
        if signal == Signal.BUY and qty_owned <= 0:
            # Calculate max affordable quantity
            # We subtract a tiny buffer (e.g., 0.1%) to account for potential 
            # fee logic you might have in your broker
            buy_qty = (available_cash * 0.999) / current_price
            
            if buy_qty > 0:
                broker.submit_order(
                    symbol=symbol,
                    qty=buy_qty, 
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    time_in_force=TimeInForce.GTC,
                    current_price=current_price
                )
            
        # --- Logic: SELL (Liquidate) ---
        elif signal == Signal.SELL and qty_owned > 0:
            broker.submit_order(
                symbol=symbol,
                qty=qty_owned,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.GTC,
                current_price=current_price
            )