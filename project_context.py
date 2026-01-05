import os
import sys
import json
from alpaca.trading.client import TradingClient
from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient, OptionHistoricalDataClient

# Project root directory
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))

# Add root to sys.path so absolute imports work everywhere
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

# Load configs once
SETTINGS_PATH = os.path.join(PROJECT_ROOT, "config", "settings.json")
SECRETS_PATH = os.path.join(PROJECT_ROOT, "config", "secrets.json")

with open(SETTINGS_PATH) as f:
    SETTINGS = json.load(f)

with open(SECRETS_PATH) as f:
    SECRETS = json.load(f)

if SETTINGS["paper"]:
    TRADING_CLIENT = TradingClient(SECRETS["alpaca-paper"]["api_key"], SECRETS["alpaca-paper"]["secret_key"])
    STOCK_HISTORIC_DATA_CLIENT = StockHistoricalDataClient(SECRETS["alpaca-paper"]["api_key"], SECRETS["alpaca-paper"]["secret_key"])
    OPTION_HISTORIC_DATA_CLIENT = OptionHistoricalDataClient(SECRETS["alpaca-paper"]["api_key"], SECRETS["alpaca-paper"]["secret_key"])
else:
    TRADING_CLIENT = TradingClient(SECRETS["alpaca"]["api_key"], SECRETS["alpaca"]["secret_key"])
    STOCK_HISTORIC_DATA_CLIENT = StockHistoricalDataClient(SECRETS["alpaca"]["api_key"], SECRETS["alpaca"]["secret_key"])
    OPTION_HISTORIC_DATA_CLIENT = OptionHistoricalDataClient(SECRETS["alpaca"]["api_key"], SECRETS["alpaca"]["secret_key"])

CRYPTO_HISTORIC_DATA_CLIENT = CryptoHistoricalDataClient()

