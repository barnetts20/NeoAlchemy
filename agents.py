from abc import ABC, abstractmethod
import pandas as pd
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from strategies import BaseStrategy, Signal
from logger import logger

class BaseAgent(ABC):
    def __init__(self, strategy: BaseStrategy):
        self.strategy = strategy

    @abstractmethod
    def handle_tick(self, symbol: str, data: pd.DataFrame, broker):
        """Standardized signature for both Backtesting and Live."""
        pass

    def get_window_size(self) -> int:
        return self.strategy.window_size

class CryptoAgent(BaseAgent):
    def __init__(self, strategy: BaseStrategy, commitment: float = 0.5):
        super().__init__(strategy)
        self.commitment = commitment  # Fraction of cash to use per trade (0.0 to 1.0)
    
    def handle_tick(self, symbol: str, data: pd.DataFrame, broker):
        # 1. Get the Signal
        signal = self.strategy.generate_signal(data)
        # 2. Check current position and broker state
        try:
            current_pos = broker.get_open_position(symbol)
            qty_owned = float(current_pos.get("qty", 0))
        except Exception as e:
            # If position doesn't exist or error fetching, assume no position
            logger.debug(f"Could not get position for {symbol}: {e}")
            qty_owned = 0.0
        
        # 3. Get Account Cash for sizing
        try:
            acc = broker.get_account()
            available_cash = float(acc["cash"])
        except Exception as e:
            logger.error(f"Failed to get account info for {symbol}: {e}")
            return
        
        # Validate data has required columns
        if 'close' not in data.columns or len(data) == 0:
            logger.warning(f"Invalid data for {symbol}: missing 'close' column or empty dataframe")
            return
        
        current_price = float(data['close'].iloc[-1])
        
        # Validate price is positive
        if current_price <= 0:
            logger.warning(f"Invalid price for {symbol}: {current_price}")
            return
        
        # Validate commitment is reasonable
        if not 0 < self.commitment <= 1:
            logger.warning(f"Invalid commitment value: {self.commitment}, must be between 0 and 1")
            return

        # --- Logic: BUY Signal ---
        if signal == Signal.OPEN_LONG:
            if qty_owned > 0:
                logger.debug(f"SIGNAL: OPEN_LONG but already have LONG position in {symbol} (qty: {qty_owned})")
            else:
                buy_qty = (available_cash * self.commitment) / current_price
                if buy_qty > 0:
                    logger.info(f"SIGNAL: OPEN_LONG {float(buy_qty):.6f} {symbol} @ ${float(current_price):.2f} (value: ${float(buy_qty * current_price):.2f})")
                    try:
                        broker.submit_order(
                            symbol=symbol,
                            qty=buy_qty, 
                            side=OrderSide.BUY,
                            order_type=OrderType.MARKET,
                            time_in_force=TimeInForce.GTC,
                            current_price=current_price
                        )
                    except Exception as e:
                        logger.error(f"Failed to submit BUY order for {symbol}: {e}", exc_info=True)

        # --- Logic: CLOSE LONG ---
        elif signal == Signal.CLOSE_LONG:
            if qty_owned <= 0:
                logger.debug(f"SIGNAL: CLOSE_LONG but no long position in {symbol}")
            else:
                logger.info(f"SIGNAL: CLOSE_LONG {float(qty_owned):.6f} {symbol} @ ${float(current_price):.2f} (value: ${float(qty_owned * current_price):.2f})")
                try:
                    broker.submit_order(
                        symbol=symbol,
                        qty=qty_owned,
                        side=OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        time_in_force=TimeInForce.GTC,
                        current_price=current_price
                    )
                except Exception as e:
                    logger.error(f"Failed to submit CLOSE_LONG order for {symbol}: {e}", exc_info=True)
        
        # --- Logic: SHORT Signals (not supported for crypto) ---
        elif signal == Signal.OPEN_SHORT:
            logger.error(f"SIGNAL: OPEN_SHORT not supported for crypto trading on {symbol}")
        
        elif signal == Signal.CLOSE_SHORT:
            logger.error(f"SIGNAL: CLOSE_SHORT not supported for crypto trading on {symbol}")

        # --- HOLD Signal ---
        else:
            logger.debug(f"SIGNAL: HOLD for {symbol}")