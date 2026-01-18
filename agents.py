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

class CryptoAgent(BaseAgent):
    def handle_tick(self, symbol: str, data: pd.DataFrame, broker):
        # 1. Get the Signal
        signal = self.strategy.generate_signal(data)
        self.commitment = .5
        # 2. Check current position and broker state
        try:
            current_pos = broker.get_open_position(symbol)
            qty_owned = float(current_pos.get("qty", 0))
        except Exception as e:
            # If position doesn't exist or error fetching, assume no position
            logger.debug(f"Could not get position for {symbol}: {e}")
            qty_owned = 0.0
        
        # 3. Get Account Cash for sizing
        acc = broker.get_account()
        available_cash = float(acc["cash"])
        current_price = float(data['close'].iloc[-1])

        # --- Logic: BUY Signal ---
        if signal == Signal.OPEN_LONG:
            if qty_owned > 0:  # Check for ANY existing long position
                logger.debug(f"SIGNAL: OPEN_LONG but already have LONG position in {symbol} (qty: {qty_owned})")
            elif qty_owned < 0:
                logger.debug(f"SIGNAL: OPEN_LONG but already have SHORT position in {symbol} (qty: {qty_owned})")
                logger.debug("CLOSING SHORT POSITION")
                broker.submit_order(
                    symbol=symbol,
                    qty=abs(qty_owned),  # Use absolute value
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    time_in_force=TimeInForce.GTC,
                    current_price=current_price
                )
            else:
                buy_qty = (available_cash * self.commitment) / current_price
                if buy_qty > 0:
                    logger.info(f"SIGNAL: OPEN_LONG {float(buy_qty):.6f} {symbol} @ ${float(current_price):.2f} (value: ${float(buy_qty * current_price):.2f})")
                    broker.submit_order(
                        symbol=symbol,
                        qty=buy_qty, 
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        time_in_force=TimeInForce.GTC,
                        current_price=current_price
                    )

        # --- Logic: SHORT Signal ---
        elif signal == Signal.OPEN_SHORT:
            if qty_owned < 0:  # Already short
                logger.debug(f"SIGNAL: OPEN_SHORT but already have SHORT position in {symbol} (qty: {qty_owned})")
            elif qty_owned > 0:  # Have long, close it
                logger.info(f"SIGNAL: OPEN_SHORT but have LONG position in {symbol} (qty: {qty_owned})")
                logger.info("CLOSING LONG POSITION")
                broker.submit_order(
                    symbol=symbol,
                    qty=qty_owned,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    time_in_force=TimeInForce.GTC,
                    current_price=current_price
                )
            else:  # qty_owned == 0, open short
                sell_qty = (available_cash * self.commitment) / current_price
                if sell_qty > 0:
                    logger.info(f"SIGNAL: OPEN_SHORT {float(sell_qty):.6f} {symbol} @ ${float(current_price):.2f} (value: ${float(sell_qty * current_price):.2f})")
                    broker.submit_order(
                        symbol=symbol,
                        qty=sell_qty,
                        side=OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        time_in_force=TimeInForce.GTC,
                        current_price=current_price
                    )

        # --- Logic: CLOSE LONG ---
        elif signal == Signal.CLOSE_LONG:
            if qty_owned <= 0:
                logger.debug(f"SIGNAL: CLOSE_LONG but no long position in {symbol}")
            else:
                logger.info(f"SIGNAL: CLOSE_LONG {float(qty_owned):.6f} {symbol} @ ${float(current_price):.2f} (value: ${float(qty_owned * current_price):.2f})")
                broker.submit_order(
                    symbol=symbol,
                    qty=qty_owned,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    time_in_force=TimeInForce.GTC,
                    current_price=current_price
                )

        # --- Logic: CLOSE SHORT ---
        elif signal == Signal.CLOSE_SHORT:
            if qty_owned >= 0:
                logger.debug(f"SIGNAL: CLOSE_SHORT but no short position in {symbol}")
            else:
                logger.info(f"SIGNAL: CLOSE_SHORT {float(abs(qty_owned)):.6f} {symbol} @ ${float(current_price):.2f} (value: ${float(abs(qty_owned) * current_price):.2f})")
                broker.submit_order(
                    symbol=symbol,
                    qty=abs(qty_owned),  # Use absolute value
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    time_in_force=TimeInForce.GTC,
                    current_price=current_price
                )

        # --- HOLD Signal ---
        else:
            logger.debug(f"SIGNAL: HOLD for {symbol}")