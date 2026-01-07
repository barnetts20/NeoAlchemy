from abc import ABC, abstractmethod
from typing import Union, List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime

# Logic Imports
from project_context import TRADING_CLIENT
from strategies.base_strategy import Signal

# Alpaca SDK Imports
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce, QueryOrderStatus

class BaseBroker(ABC):
    @abstractmethod
    def get_account(self) -> Dict: pass
    
    @abstractmethod
    def get_clock(self) -> Dict: pass

    # --- Position Management ---
    @abstractmethod
    def get_all_positions(self) -> List[Dict]: pass
    
    @abstractmethod
    def get_open_position(self, symbol: str) -> Dict: pass
    
    @abstractmethod
    def close_all_positions(self, cancel_orders: bool = True) -> List[Dict]: pass
    
    @abstractmethod
    def close_position(self, symbol: str) -> Dict: pass

    # --- Order Management ---
    @abstractmethod
    def submit_order(self, symbol: str, qty: float, side: str, order_type: str, 
                     time_in_force: str, limit_price: Optional[float] = None, **kwargs) -> Dict: pass
    
    @abstractmethod
    def get_orders(self, status: str = "open", limit: int = 50) -> List[Dict]: pass
    
    @abstractmethod
    def get_order_by_id(self, order_id: Union[UUID, str]) -> Dict: pass
    
    @abstractmethod
    def cancel_orders(self) -> List[Dict]: pass
    
    @abstractmethod
    def cancel_order_by_id(self, order_id: Union[UUID, str]) -> None: pass


class LiveAlpacaBroker(BaseBroker):
    def __init__(self):
        self.client = TRADING_CLIENT

    def get_account(self):
        return self.client.get_account().model_dump()

    def get_clock(self):
        return self.client.get_clock().model_dump()

    def get_all_positions(self):
        return [p.model_dump() for p in self.client.get_all_positions()]

    def get_open_position(self, symbol: str):
        try:
            return self.client.get_open_position(symbol).model_dump()
        except Exception:
            # Return a "neutral" position dict if not found, matching Alpaca structure roughly
            return {"qty": 0, "avg_entry_price": 0, "symbol": symbol}

    def close_all_positions(self, cancel_orders=True):
        return [r.model_dump() for r in self.client.close_all_positions(cancel_orders=cancel_orders)]

    def close_position(self, symbol: str):
        return self.client.close_position(symbol).model_dump()

    def submit_order(self, symbol, qty, side, order_type, time_in_force, limit_price=None, **kwargs):
        # We ignore **kwargs here (like current_price) as the Live Broker doesn't need them
        
        if order_type.lower() == "market":
            req = MarketOrderRequest(symbol=symbol, qty=qty, side=side, time_in_force=time_in_force)
        else:
            req = LimitOrderRequest(symbol=symbol, qty=qty, side=side, time_in_force=time_in_force, limit_price=limit_price)
        
        return self.client.submit_order(req).model_dump()

    def get_orders(self, status="open", limit=50):
        st = QueryOrderStatus.OPEN if status == "open" else QueryOrderStatus.ALL
        req = GetOrdersRequest(status=st, limit=limit)
        return [o.model_dump() for o in self.client.get_orders(req)]

    def get_order_by_id(self, order_id):
        return self.client.get_order_by_id(order_id).model_dump()

    def cancel_orders(self):
        return [r.model_dump() for r in self.client.cancel_orders()]

    def cancel_order_by_id(self, order_id):
        self.client.cancel_order_by_id(order_id)


class LocalSimBroker(BaseBroker):
    def __init__(self, initial_cash=100000.0):
        self.cash = initial_cash
        self.positions = {} # { symbol: {qty, avg_entry_price} }
        self.orders = []    # List of order dicts
        self.current_prices = {} # { symbol: price } for equity calc

    def update_price(self, symbol: str, price: float):
        """Essential for Backtesting: Update the 'tape' so we can calculate equity."""
        self.current_prices[symbol] = price

    def get_account(self):
        # Calculate Equity = Cash + Unrealized Value of Positions
        equity = self.cash
        for symbol, pos in self.positions.items():
            # Use current price if available, otherwise fallback to entry price (no change)
            curr_price = self.current_prices.get(symbol, pos['avg_entry_price'])
            equity += pos['qty'] * curr_price

        return {
            "cash": self.cash, 
            "buying_power": self.cash, 
            "equity": equity
        }

    def get_clock(self):
        return {"is_open": True, "timestamp": datetime.now()}

    def get_all_positions(self):
        return list(self.positions.values())

    def get_open_position(self, symbol: str):
        return self.positions.get(symbol, {"qty": 0, "avg_entry_price": 0, "symbol": symbol})

    def submit_order(self, symbol, qty, side, order_type, time_in_force, limit_price=None, **kwargs):
        # Sim broker looks for 'current_price' in kwargs to fill market orders immediately
        current_price = kwargs.get('current_price')
        
        # If no price passed, try to use the last known price from update_price
        if current_price is None:
            current_price = self.current_prices.get(symbol)
            
        if current_price is None and order_type.lower() == "market":
            raise ValueError("SimBroker: Cannot fill MARKET order without a current_price")

        fill_price = limit_price if order_type.lower() == "limit" else current_price
        order_id = str(uuid.uuid4())
        
        # Simple Execution Logic
        cost = qty * fill_price
        
        # Handle 'side' whether it's a String ("buy") or Enum (OrderSide.BUY)
        is_buy = str(side).lower() == "buy"

        if is_buy:
            if self.cash < cost:
                raise ValueError(f"SimBroker: Insufficient funds. Cash: {self.cash}, Cost: {cost}")
            
            self.cash -= cost
            pos = self.get_open_position(symbol)
            
            # Weighted Average Price Calculation
            old_qty = pos['qty']
            old_avg = pos['avg_entry_price']
            new_qty = old_qty + qty
            
            # Avoid division by zero if this is the first trade
            if new_qty > 0:
                new_avg = ((old_qty * old_avg) + cost) / new_qty
            else:
                new_avg = fill_price

            pos.update({
                "symbol": symbol,
                "qty": new_qty,
                "avg_entry_price": new_avg
            })
            self.positions[symbol] = pos
        else:
            # Sell Logic
            self.cash += cost
            # For simplicity in this version, we assume full sell. 
            # (Backtester can implement partials later)
            self.positions.pop(symbol, None)

        order = {
            "id": order_id, 
            "symbol": symbol, 
            "status": "filled", 
            "filled_avg_price": fill_price,
            "side": side,
            "qty": qty
        }
        self.orders.append(order)
        return order

    def close_all_positions(self, cancel_orders=True):
        if cancel_orders: self.cancel_orders()
        closed = [{"symbol": k, "status": "closed"} for k in self.positions.keys()]
        # Cash out all positions at current prices
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            price = self.current_prices.get(symbol, pos['avg_entry_price'])
            self.cash += pos['qty'] * price
            
        self.positions.clear()
        return closed

    def close_position(self, symbol: str):
        pos = self.positions.pop(symbol, None)
        if pos:
            price = self.current_prices.get(symbol, pos['avg_entry_price'])
            self.cash += pos['qty'] * price
            return {"symbol": symbol, "status": "closed"}
        return {"symbol": symbol, "status": "not_found"}

    def get_orders(self, status="open", limit=50):
        # Basic slicing
        return self.orders[-limit:]

    def get_order_by_id(self, order_id):
        for o in self.orders:
            if o['id'] == str(order_id): return o
        return {}

    def cancel_orders(self):
        self.orders = [o for o in self.orders if o['status'] != 'open']
        return [{"status": "all_cancelled"}]

    def cancel_order_by_id(self, order_id):
        self.orders = [o for o in self.orders if o['id'] != str(order_id)]