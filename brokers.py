from abc import ABC, abstractmethod
from alpaca.trading.enums import AssetClass, OrderSide, OrderType, TimeInForce, OrderStatus, QueryOrderStatus
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, StopOrderRequest, TrailingStopOrderRequest, StopLimitOrderRequest, GetOrdersRequest
from datetime import datetime
from project_context import TRADING_CLIENT
from typing import Union, List, Dict
from uuid import UUID, uuid4

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
    def submit_order(self, symbol, qty, side: OrderSide, order_type: OrderType, time_in_force: TimeInForce, limit_price=None, stop_price=None, trail_price=None, trail_percent=None, **kwargs) -> Dict: pass
    
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
        symbol = symbol.replace("/", "")
        try:
            return self.client.get_open_position(symbol).model_dump()
        except Exception as e:
            # Position doesn't exist - return empty position dict
            if "does not exist" in str(e) or "40410000" in str(e):
                return {
                    "symbol": symbol,
                    "qty": "0",
                    "side": "long",
                    "market_value": "0",
                    "cost_basis": "0",
                    "unrealized_pl": "0",
                    "unrealized_plpc": "0",
                    "current_price": "0",
                    "avg_entry_price": "0"
                }
            # Re-raise if it's a different error
            raise

    def close_all_positions(self, cancel_orders=True):
        return [r.model_dump() for r in self.client.close_all_positions(cancel_orders=cancel_orders)]

    def close_position(self, symbol: str):
        symbol = symbol.replace("/", "")
        return self.client.close_position(symbol).model_dump()

    def submit_order(self, symbol, qty, side: OrderSide, order_type: OrderType, time_in_force: TimeInForce, limit_price=None, stop_price=None, trail_price=None, trail_percent=None, **kwargs):        
        if qty <= 0:
            raise ValueError(f"Order quantity must be positive, got: {qty}")
        
        if order_type == OrderType.MARKET:
            req = MarketOrderRequest(
                symbol=symbol, 
                qty=qty, 
                side=side, 
                time_in_force=time_in_force
            )
        elif order_type == OrderType.LIMIT:
            if limit_price is None:
                raise ValueError(f"limit_price is required for LIMIT orders")
            req = LimitOrderRequest(
                symbol=symbol, 
                qty=qty, 
                side=side, 
                time_in_force=time_in_force, 
                limit_price=limit_price
            )
        elif order_type == OrderType.STOP:
            if stop_price is None:
                raise ValueError(f"stop_price is required for STOP orders")
            req = StopOrderRequest(
                symbol=symbol, 
                qty=qty, 
                side=side, 
                time_in_force=time_in_force, 
                stop_price=stop_price
            )
        elif order_type == OrderType.STOP_LIMIT:
            if stop_price is None or limit_price is None:
                raise ValueError(f"stop_price and limit_price are required for STOP_LIMIT orders")
            req = StopLimitOrderRequest(
                symbol=symbol, 
                qty=qty, 
                side=side, 
                time_in_force=time_in_force, 
                stop_price=stop_price, 
                limit_price=limit_price
            )
        elif order_type == OrderType.TRAILING_STOP:
            if trail_price is None and trail_percent is None:
                raise ValueError(f"Either trail_price or trail_percent is required for TRAILING_STOP orders")
            req = TrailingStopOrderRequest(
                symbol=symbol, 
                qty=qty, 
                side=side, 
                time_in_force=time_in_force, 
                trail_price=trail_price, 
                trail_percent=trail_percent
            )
        else:
            raise ValueError(f"Invalid order_type: {order_type}. Must be one of: MARKET, LIMIT, STOP, STOP_LIMIT, TRAILING_STOP")

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

class LocalSimBroker:
    """
    A high-fidelity simulation broker that uses official Alpaca Enums.
    mirrors Alpaca's fee structure:
      - Crypto: 0.25% Taker fee (Tier 1 default)
      - Stocks: No commission, but sells incur reg fees (SEC + TAF)
    """
    def __init__(self, initial_cash=100000.0):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions = {}       # { symbol: {qty, avg_entry_price, ...} }
        self.orders = []          # List of order dicts
        self.ledger = []          # Transaction history
        self.current_prices = {}  # The "Tape": { symbol: price }
        
        # Fee Constants (Alpaca / Regulatory Defaults)
        self.CRYPTO_FEE_RATE = 0.006  # 0.6% Taker Fee (more realistic)
        self.SEC_FEE_RATE = 8.00 / 1_000_000  # $8 per million (Sells only)
        self.TAF_RATE = 0.000166  # Per share (Sells only)
        self.TAF_MAX = 8.30

    # --- HELPER: Fee Calculation ---
    def _calculate_fees(self, symbol: str, qty: float, price: float, side: OrderSide) -> float:
        is_crypto = self._is_crypto(symbol)  # Use improved detection method
        notional = qty * price
        fees = 0.0

        if is_crypto:
            # Crypto: Fees on Buy AND Sell
            fees = notional * self.CRYPTO_FEE_RATE
        else:
            # Stocks: Fees on SELL only (Regulatory)
            if side == OrderSide.SELL:
                # SEC Fee (rounded to nearest penny)
                sec_fee = max(0.01, round(notional * self.SEC_FEE_RATE, 2))
                
                # TAF Fee (rounded to nearest penny, capped at $8.30)
                taf_fee = qty * self.TAF_RATE
                taf_fee = max(0.01, round(taf_fee, 2))
                taf_fee = min(taf_fee, self.TAF_MAX)
                
                fees = sec_fee + taf_fee

        return float(fees)
    
    def _is_crypto(self, symbol: str) -> bool:
        """
        Helper to determine if a symbol is crypto.
        Checks for crypto-specific patterns while avoiding false positives.
        """
        symbol_upper = symbol.upper()
        # Check for crypto pair separators (most reliable indicator)
        if '/' in symbol:
            # Check that it's not a stock symbol with a slash (unlikely but possible)
            crypto_suffixes = ['/USD', '/BTC', '/ETH', '/USDT', '/USDC', '/DAI']
            return any(symbol_upper.endswith(suffix) for suffix in crypto_suffixes)
        # Fallback: check for common crypto-only patterns (less reliable)
        # Avoid matching "USDT" as a standalone stock symbol
        return False
    
    # --- DATA INGESTION ---
    def update_price(self, symbol: str, price: float):
        """Essential: Updates the internal 'tape' so we can calculate Equity/fills."""
        # Force float storage to prevent downstream type errors
        self.current_prices[symbol] = float(price)

    # --- ACCOUNTING ---
    def get_account(self):
        # Force base equity to float to avoid Decimal + Float errors
        equity = float(self.cash)
        long_market_value = 0.0

        for symbol, pos in self.positions.items():
            # Use real-time price if available, else fallback to entry
            raw_price = self.current_prices.get(symbol, pos['avg_entry_price'])
            curr_price = float(raw_price)
            
            # Ensure quantity is float for calculation
            pos_qty = float(pos['qty'])
            
            mkt_val = pos_qty * curr_price
            long_market_value += mkt_val
            equity += mkt_val

        return {
            "id": str(uuid4()),
            "status": "ACTIVE",
            "currency": "USD",
            "cash": str(self.cash),
            "buying_power": str(self.cash), # Simplified (no margin)
            "equity": str(equity),
            "long_market_value": str(long_market_value),
            "initial_capital": str(self.initial_cash),
            "created_at": datetime.now().isoformat()
        }

    def get_clock(self):
        return {"is_open": True, "timestamp": datetime.now()}

    # --- POSITIONS ---
    def _construct_position_object(self, symbol, pos_data):
        """
        Recreates the exact JSON structure of an Alpaca Position object.
        Calculates Unrealized P&L dynamically.
        """
        qty = float(pos_data['qty'])
        avg_entry = float(pos_data['avg_entry_price'])
        current_price = self.current_prices.get(symbol, avg_entry)
        
        market_value = qty * current_price
        cost_basis = qty * avg_entry
        unrealized_pl = market_value - cost_basis
        # Avoid division by zero with epsilon check for floating point safety
        unrealized_plpc = (unrealized_pl / cost_basis) if abs(cost_basis) > 1e-9 else 0.0

        # Note: All numbers are returned as strings in Alpaca API, 
        # but we keep them as floats here for sim ease unless you strictly need strings.
        return {
            "asset_id": str(uuid4()),
            "symbol": symbol,
            "exchange": "NASDAQ", # Mock
            "asset_class": pos_data.get('asset_class', AssetClass.US_EQUITY),
            "avg_entry_price": avg_entry,
            "qty": qty,
            "side": "long",
            "market_value": market_value,
            "cost_basis": cost_basis,
            "unrealized_pl": unrealized_pl,
            "unrealized_plpc": unrealized_plpc,
            "current_price": current_price,
            "change_today": 0.0, # Hard to calc without 'prev_close'
            "created_at": pos_data.get('created_at')  # Position creation timestamp
        }

    def get_all_positions(self):
        return [self._construct_position_object(k, v) for k, v in self.positions.items()]

    def get_open_position(self, symbol: str):
        if symbol in self.positions:
            return self._construct_position_object(symbol, self.positions[symbol])
        
        # Simulate Alpaca behavior: 404/Empty if not found
        # (Your bot logic likely handles 'if not found' checks)
        return {
            "symbol": symbol, 
            "qty": 0, 
            "avg_entry_price": 0, 
            "market_value": 0,
            "status": "closed"
        }

    # --- ORDER EXECUTION ---
    def submit_order(self, symbol, qty, side: OrderSide, order_type: OrderType, time_in_force: TimeInForce, limit_price=None, stop_price=None, trail_price=None, trail_percent=None, **kwargs) -> Dict:
        if qty <= 0:
            raise ValueError(f"Order quantity must be positive, got: {qty}")
        
        # Ensure quantity is a float for math operations
        qty = float(qty)
        
        # 2. Get Execution Price
        raw_price = kwargs.get('current_price') or self.current_prices.get(symbol)
        
        if raw_price is None:
            if order_type == OrderType.MARKET:
                raise ValueError(f"SimBroker: Cannot fill MARKET order for {symbol} - No price data.")
            current_price = None
        else:
            current_price = float(raw_price)
        
        # Determine fill price
        if order_type == OrderType.LIMIT:
            fill_price = float(limit_price)
        else:
            fill_price = current_price
            
        is_crypto = self._is_crypto(symbol)
        order_id = str(uuid4())
        
        filled_qty = qty
        fee_amt_cash = 0.0

        # 3. Handle Execution Logic
        if side == OrderSide.BUY:
            total_cash_required = qty * fill_price
            
            # Use float(self.cash) for comparison to avoid Decimal errors
            if float(self.cash) < total_cash_required:
                raise ValueError(f"Insufficient Cash. Need: {total_cash_required}, Have: {self.cash}")
            
            # Deduct full cash amount immediately (cast to float)
            self.cash = float(self.cash) - total_cash_required
            
            # CRYPTO FEE BEHAVIOR: 
            # You pay for 'qty' but receive 'qty minus fee'
            if is_crypto:
                fee_rate = self.CRYPTO_FEE_RATE
                filled_qty = qty * (1 - fee_rate)
            else:
                filled_qty = qty

            self._update_position(symbol, filled_qty, fill_price, OrderSide.BUY, kwargs.get('created_at'))

        elif side == OrderSide.SELL:
            pos = self.positions.get(symbol)
            if not pos or float(pos['qty']) < qty:
                 raise ValueError(f"Insufficient Position. Held: {pos['qty'] if pos else 0}, Sell: {qty}")
            
            gross_proceeds = qty * fill_price
            
            # For Sells, fees are deducted from the CASH proceeds
            if is_crypto:
                fee_amt_cash = gross_proceeds * self.CRYPTO_FEE_RATE
            else:
                sec_fee = max(0.01, round(gross_proceeds * self.SEC_FEE_RATE, 2))
                taf_fee = min(max(0.01, round(qty * self.TAF_RATE, 2)), self.TAF_MAX)
                fee_amt_cash = sec_fee + taf_fee

            # Add proceeds to cash (cast to float)
            self.cash = float(self.cash) + (gross_proceeds - fee_amt_cash)
            self._update_position(symbol, qty, fill_price, OrderSide.SELL)
            filled_qty = qty

        # 4. Create Record
        order = {
            "id": order_id,
            "client_order_id": str(uuid4()),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "submitted_at": datetime.now().isoformat(),
            "filled_at": datetime.now().isoformat(),
            "expired_at": None,
            "canceled_at": None,
            "failed_at": None,
            "asset_id": str(uuid4()),
            "symbol": symbol,
            "asset_class": AssetClass.CRYPTO if is_crypto else AssetClass.US_EQUITY,
            "qty": str(qty),
            "filled_qty": str(filled_qty),
            "type": order_type.value,
            "side": side.value,
            "time_in_force": time_in_force.value if hasattr(time_in_force, 'value') else time_in_force,
            "limit_price": str(limit_price) if limit_price else None,
            "filled_avg_price": str(fill_price),
            "status": OrderStatus.FILLED.value,
            "extended_hours": False,
            "legs": None,
            "_sim_fee_cash": fee_amt_cash 
        }
        
        self.orders.append(order)
        self.ledger.append({
            "time": datetime.now(), 
            "symbol": symbol, 
            "side": side.value, 
            "qty": filled_qty, 
            "price": fill_price, 
            "fee_cash": fee_amt_cash
        })
        
        return order

    def _update_position(self, symbol, qty, price, side, created_at=None):
        # Default state for a new position
        pos = self.positions.get(symbol, {
            "symbol": symbol,
            "qty": 0.0,
            "avg_entry_price": 0.0,
            "asset_class": AssetClass.CRYPTO if self._is_crypto(symbol) else AssetClass.US_EQUITY,
            "created_at": None  # Will be set on first position open
        })
        
        if side == OrderSide.BUY:
            # qty is the net amount (already reduced by fee if crypto)
            current_total_cost = pos['qty'] * pos['avg_entry_price']
            new_qty = pos['qty'] + qty

            # Set created_at timestamp if this is the first position open
            if pos['qty'] == 0.0 and new_qty > 0:
                pos['created_at'] = created_at or datetime.now().isoformat()

            # Weighted average based on what was actually received
            # We use the market price for the cost basis of the new shares/coins
            if new_qty > 0:
                pos['avg_entry_price'] = (current_total_cost + (qty * price)) / new_qty
            else:
                # Edge case: should not happen, but protect against division by zero
                pos['avg_entry_price'] = price
            pos['qty'] = new_qty
            self.positions[symbol] = pos
            
        elif side == OrderSide.SELL:
            # qty is the amount to subtract
            new_qty = pos['qty'] - qty
            # Epsilon check: if qty is effectively zero, remove the position
            # This prevents 0.0000000000001 BTC from causing 'Insufficient Position' errors
            if new_qty <= 1e-9:
                self.positions.pop(symbol, None)
            else:
                pos['qty'] = new_qty
                self.positions[symbol] = pos

    # --- ORDER MANAGEMENT ---
    def get_orders(self, status: Union[str, OrderStatus] = "open", limit=50):
        # Convert Enum to string if needed
        status_str = status.value if isinstance(status, OrderStatus) else status
        
        filtered = []
        for o in reversed(self.orders): # Newest first
            o_status = o['status']
            if status_str == "open" and o_status in ["new", "accepted", "pending_new"]:
                filtered.append(o)
            elif status_str == "closed" and o_status in ["filled", "canceled", "expired"]:
                filtered.append(o)
            elif status_str == "all":
                filtered.append(o)
        
        return filtered[:limit]

    def cancel_orders(self):
        # In this Sim, orders fill instantly, so there are rarely "open" orders to cancel.
        # But strictly speaking:
        canceled_count = 0
        for o in self.orders:
            if o['status'] in [OrderStatus.NEW.value, OrderStatus.ACCEPTED.value]:
                o['status'] = OrderStatus.CANCELED.value
                canceled_count += 1
        return [{"status": "cancelled", "count": canceled_count}]

    def close_all_positions(self, cancel_orders: bool = True) -> List[Dict]:
        """
        Liquidates all positions using Market Orders to ensure fees/PNL are calculated.
        Continues closing positions even if one fails.
        """
        if cancel_orders:
            self.cancel_orders()

        closed_orders = []
        errors = []
        # Create a static list of keys to avoid runtime error while modifying the dict
        for symbol in list(self.positions.keys()):
            try:
                # We reuse close_position to ensure consistent logic
                result = self.close_position(symbol)
                if result:
                    closed_orders.append(result)
            except Exception as e:
                errors.append(f"{symbol}: {str(e)}")
                # Continue with other positions even if one fails
        
        if errors:
            # Log errors but don't fail the entire operation
            import logging
            logging.warning(f"Errors closing some positions: {', '.join(errors)}")
        
        return closed_orders

    def close_position(self, symbol: str) -> Dict:
        """
        closes a specific position by submitting a SELL Market order.
        """
        pos = self.positions.get(symbol)
        if not pos:
            # Alpaca returns 404, we return empty/None or raise error depending on preference.
            # BaseBroker defines return as Dict, so we return a "not found" object
            return {}

        qty = pos['qty']
        
        # Submit a MARKET SELL order. 
        # This triggers the submit_order logic which handles Fees, Cash updates, and Ledger logging.
        return self.submit_order(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.GTC
        )

    def get_order_by_id(self, order_id: Union[UUID, str]) -> Dict:
        """
        Finds an order by its ID (client_order_id or system id).
        """
        target_id = str(order_id)
        for o in self.orders:
            if o['id'] == target_id or o.get('client_order_id') == target_id:
                return o
        
        # Raise error to match Alpaca SDK behavior (or return empty dict if preferred)
        raise ValueError(f"Order not found: {order_id}")

    def cancel_order_by_id(self, order_id: Union[UUID, str]) -> None:
        """
        Cancels a specific order if it is still open.
        """
        order = self.get_order_by_id(order_id)
        
        # Check if status allows cancellation
        if order['status'] in [OrderStatus.NEW.value, OrderStatus.ACCEPTED.value, OrderStatus.PENDING_NEW.value]:
            order['status'] = OrderStatus.CANCELED.value
            # In a real broker, we might add a cancellation record to the ledger, 
            # but for Sim we just update the status.
        else:
            # Alpaca raises an error if you try to cancel an already filled/closed order
            raise ValueError(f"Cannot cancel order {order_id} with status {order['status']}")