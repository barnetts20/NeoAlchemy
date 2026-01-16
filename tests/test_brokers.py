import pytest
from unittest.mock import MagicMock, patch
from brokers import LocalSimBroker, LiveAlpacaBroker
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce

# ==========================================
# 1. Simulation Broker Tests (Logic Focused)
# ==========================================
import pytest
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce

class TestLocalSimBroker:
    INITIAL_CASH = 1000000.0
    CRYPTO_FEE_RATE = 0.0025  # 0.25%

    @pytest.fixture
    def broker(self):
        # Assumes LocalSimBroker is imported or in the same scope
        return LocalSimBroker(initial_cash=self.INITIAL_CASH)

    def test_initialization(self, broker):
        acc = broker.get_account()
        assert float(acc["cash"]) == self.INITIAL_CASH
        assert float(acc["equity"]) == self.INITIAL_CASH

    def test_buy_execution_logic(self, broker):
        """Updated: Accounts for 0.25% asset deduction on Crypto Buy."""
        price = 50000.0
        qty = 1.0
        broker.submit_order(
            symbol="BTC/USD",
            qty=qty,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.GTC,
            current_price=price 
        )
        # Cash is deducted in full for the requested qty
        expected_cash = self.INITIAL_CASH - (qty * price)
        # Qty is reduced by the fee
        expected_qty = qty * (1 - self.CRYPTO_FEE_RATE)
        
        assert float(broker.get_account()["cash"]) == expected_cash
        assert broker.get_open_position("BTC/USD")["qty"] == expected_qty

    def test_insufficient_funds(self, broker):
        # Trigger an order that exceeds INITIAL_CASH
        huge_qty = (self.INITIAL_CASH / 10) 
        price = 20.0 # Total 2x INITIAL_CASH
        # Match against the exact error message in your LocalSimBroker
        with pytest.raises(ValueError, match="Insufficient Cash"):
            broker.submit_order(
                symbol="BTC/USD",
                qty=huge_qty,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.GTC,
                current_price=price
            )

    def test_equity_updates_with_price(self, broker):
        """Updated: Equity calculation must account for the lower net qty."""
        buy_price = 50000.0
        new_price = 40000.0
        # Buy 1 BTC
        broker.submit_order("BTC/USD", 1.0, OrderSide.BUY, OrderType.MARKET, TimeInForce.GTC, current_price=buy_price)
        
        broker.update_price("BTC/USD", new_price)
        
        net_qty = 1.0 * (1 - self.CRYPTO_FEE_RATE)
        # Equity = Remaining Cash + (Net Qty * New Price)
        expected_equity = (self.INITIAL_CASH - buy_price) + (net_qty * new_price)
        
        assert float(broker.get_account()["equity"]) == expected_equity

    def test_weighted_average_price(self, broker):
        """Updated: Verifies avg entry remains correct despite fee deduction."""
        p1, p2 = 50000.0, 60000.0
        broker.submit_order("BTC/USD", 1.0, OrderSide.BUY, OrderType.MARKET, TimeInForce.GTC, current_price=p1)
        broker.submit_order("BTC/USD", 1.0, OrderSide.BUY, OrderType.MARKET, TimeInForce.GTC, current_price=p2)
        
        pos = broker.get_open_position("BTC/USD")
        expected_qty = 2.0 * (1 - self.CRYPTO_FEE_RATE)
        
        assert pos["qty"] == expected_qty
        # Price should be 55000.0 because both lots were identical sizes
        assert pos["avg_entry_price"] == (p1 + p2) / 2

    def test_partial_sell_logic(self, broker):
        """Updated: Accounts for cash fee deduction on Sell side."""
        buy_price = 50000.0
        sell_price = 60000.0
        sell_qty = 0.4
        
        # 1. Buy 1 BTC (Get 0.9975)
        broker.submit_order("BTC/USD", 1.0, OrderSide.BUY, OrderType.MARKET, TimeInForce.GTC, current_price=buy_price)
        
        # 2. Sell 0.4 BTC
        broker.submit_order("BTC/USD", sell_qty, OrderSide.SELL, OrderType.MARKET, TimeInForce.GTC, current_price=sell_price)
        
        pos = broker.get_open_position("BTC/USD")
        assert round(pos["qty"], 4) == 0.5975
        
        gross_proceeds = sell_qty * sell_price
        sell_fee = gross_proceeds * self.CRYPTO_FEE_RATE
        expected_cash = self.INITIAL_CASH - buy_price + (gross_proceeds - sell_fee)
        
        assert float(broker.get_account()["cash"]) == expected_cash

    def test_close_position_liquidates_at_current_price(self, broker):
        """Updated: Verifies full liquidation and cash fee application."""
        buy_price = 50000.0
        exit_price = 70000.0
        broker.submit_order("BTC/USD", 1.0, OrderSide.BUY, OrderType.MARKET, TimeInForce.GTC, current_price=buy_price)
        
        broker.update_price("BTC/USD", exit_price)
        
        # We hold 0.9975
        pos_to_sell = broker.get_open_position("BTC/USD")["qty"]
        broker.close_position("BTC/USD")
        
        gross_proceeds = pos_to_sell * exit_price
        sell_fee = gross_proceeds * self.CRYPTO_FEE_RATE
        expected_cash = (self.INITIAL_CASH - buy_price) + (gross_proceeds - sell_fee)
        
        assert float(broker.get_account()["cash"]) == expected_cash
        assert broker.get_open_position("BTC/USD")["qty"] == 0
    
    def test_market_order_without_price_fails(self, broker):
        """Original preserved: Ensure price-less orders fail."""
        with pytest.raises(ValueError, match="SimBroker: Cannot fill MARKET order"):
            broker.submit_order("AAPL", 10, OrderSide.BUY, OrderType.MARKET, TimeInForce.GTC)

    def test_short_selling_protection(self, broker):
        """Original preserved: Verify insufficient position check."""
        broker.submit_order("AAPL", 10, OrderSide.BUY, OrderType.MARKET, TimeInForce.GTC, current_price=150.0)
        
        with pytest.raises(ValueError, match="Insufficient Position"):
            broker.submit_order("AAPL", 20, OrderSide.SELL, OrderType.MARKET, TimeInForce.GTC, current_price=155.0)

    def test_equity_calculation_with_missing_tape_price(self, broker):
        """Original preserved: Fallback to avg_entry_price."""
        broker.submit_order("AAPL", 1, OrderSide.BUY, OrderType.MARKET, TimeInForce.GTC, current_price=100.0)
        broker.current_prices.pop("AAPL", None) 
        
        acc = broker.get_account()
        # Since stocks have no buy fee, qty remains 1.0. Equity should equal cash + 100.0
        assert float(acc["equity"]) == self.INITIAL_CASH

class TestSimBrokerIntegration:
    INITIAL_CASH = 100000.0

    @pytest.fixture
    def broker(self):
        return LocalSimBroker(initial_cash=self.INITIAL_CASH)

    def test_stock_lifecycle_integration(self, broker):
        """
        Scenario: Buy 100 shares of AAPL at $150, price moves to $160, sell all.
        Expectation: No buy fees, regulatory fees on sell, equity tracks price.
        """
        symbol = "AAPL"
        buy_price = 150.0
        sell_price = 160.0
        qty = 100.0

        # 1. State: Post-Buy
        broker.update_price(symbol, buy_price)
        broker.submit_order(symbol, qty, OrderSide.BUY, OrderType.MARKET, TimeInForce.GTC)
        
        pos = broker.get_open_position(symbol)
        acc = broker.get_account()
        
        assert pos["qty"] == 100.0  # Stocks: No fee deduction from asset
        assert float(acc["cash"]) == self.INITIAL_CASH - (qty * buy_price)
        assert float(acc["equity"]) == self.INITIAL_CASH # Price hasn't moved yet
        assert pos["avg_entry_price"] == 150.0

        # 2. State: Price Appreciation
        broker.update_price(symbol, sell_price)
        acc_updated = broker.get_account()
        # Equity = $85,000 cash + ($160 * 100) = $101,000
        assert float(acc_updated["equity"]) == 101000.0

        # 3. State: Post-Sell (Liquidate)
        broker.submit_order(symbol, qty, OrderSide.SELL, OrderType.MARKET, TimeInForce.GTC)
        
        # Calculate Reg Fees: SEC ($8 per million) + TAF ($0.000166 per share)
        # proceeds = 16000. SEC = max(0.01, 16000 * 0.000008) = 0.128 -> 0.13
        # TAF = max(0.01, 100 * 0.000166) = 0.0166 -> 0.02
        # Total fee approx 0.15
        final_acc = broker.get_account()
        assert symbol not in broker.positions
        assert float(final_acc["cash"]) < (85000.0 + 16000.0) # Confirms fees were taken
        assert float(final_acc["cash"]) > (85000.0 + 15999.0) # Confirms fees weren't huge

    def test_crypto_lifecycle_integration(self, broker):
        """
        Scenario: Buy 1 BTC at $50,000, price moves to $60,000, sell all.
        Expectation: 0.25% fee taken from asset on buy, 0.25% fee from cash on sell.
        """
        symbol = "BTC/USD"
        buy_price = 50000.0
        sell_price = 60000.0
        requested_qty = 1.0
        fee_rate = 0.0025

        # 1. State: Post-Buy
        broker.update_price(symbol, buy_price)
        broker.submit_order(symbol, requested_qty, OrderSide.BUY, OrderType.MARKET, TimeInForce.GTC)
        
        pos = broker.get_open_position(symbol)
        acc = broker.get_account()
        
        net_qty = requested_qty * (1 - fee_rate) # 0.9975
        assert pos["qty"] == net_qty 
        assert float(acc["cash"]) == self.INITIAL_CASH - 50000.0
        # Equity = $50k cash + (0.9975 * $50k) = $99,875 (Immediate hit due to fee)
        assert float(acc["equity"]) == 99875.0

        # 2. State: Price Appreciation
        broker.update_price(symbol, sell_price)
        acc_mid = broker.get_account()
        # Equity = $50k cash + (0.9975 * $60k) = $50k + $59,850 = $109,850
        assert float(acc_mid["equity"]) == 109850.0

        # 3. State: Post-Sell
        # We must sell exactly what we hold (the net_qty)
        broker.submit_order(symbol, net_qty, OrderSide.SELL, OrderType.MARKET, TimeInForce.GTC)
        
        gross_proceeds = net_qty * sell_price # 59850.0
        sell_fee = gross_proceeds * fee_rate # 149.625
        expected_final_cash = 50000.0 + (gross_proceeds - sell_fee)
        
        final_acc = broker.get_account()
        assert symbol not in broker.positions
        assert float(final_acc["cash"]) == expected_final_cash
# ==========================================
# 2. Live Broker Tests (Mock Focused)
# ==========================================
class TestLiveAlpacaBroker:
    """
    These tests ensure the Live Broker correctly calls the Alpaca SDK methods.
    We MOCK the actual SDK so we don't spend real money or hit API limits.
    """

    @pytest.fixture
    def mock_client(self):
        # This replaces the 'TRADING_CLIENT' inside the brokers module with a Mock
        with patch("brokers.TRADING_CLIENT") as mock:
            yield mock

    @pytest.fixture
    def broker(self, mock_client):
        # The broker will now use the mocked client automatically
        return LiveAlpacaBroker()

    def test_get_account_calls_sdk(self, broker, mock_client):
        # Setup the mock to return a fake object with a .model_dump() method
        mock_account = MagicMock()
        mock_account.model_dump.return_value = {"cash": "5000"}
        mock_client.get_account.return_value = mock_account

        # Run method
        result = broker.get_account()

        # Assertions
        mock_client.get_account.assert_called_once()
        assert result["cash"] == "5000"

    def test_submit_order_mapping(self, broker, mock_client):
        # Verify that our broker passes the Enum .value or string correctly to the SDK
        mock_client.submit_order.return_value.model_dump.return_value = {"id": "123"}
        
        broker.submit_order(
            symbol="AAPL",
            qty=10,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY
        )

        # Check that the SDK was called with a MarketOrderRequest
        args, _ = mock_client.submit_order.call_args
        request_object = args[0]
        
        # Verify the content of the request sent to Alpaca
        assert request_object.symbol == "AAPL"
        assert request_object.qty == 10
        assert request_object.side == OrderSide.BUY

    def test_get_open_position_not_found(self, broker, mock_client):
        """Ensure we get a neutral dict instead of a crash if position is missing."""
        # Mock the SDK to raise an exception (Alpaca returns 404 if position is empty)
        mock_client.get_open_position.side_effect = Exception("Position not found")
        
        res = broker.get_open_position("FAKE_TICKER")
        assert res["qty"] == 0
        assert res["symbol"] == "FAKE_TICKER"