import os
import sys
import json
from alpaca.trading.client import TradingClient
from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient, OptionHistoricalDataClient
from alpaca.data.live import CryptoDataStream, StockDataStream

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

# Determine which account to use
isPaper = SETTINGS["paper"]

account_key = "alpaca_paper" if isPaper else "alpaca"
api_key = SECRETS[account_key]["api_key"]
secret_key = SECRETS[account_key]["secret_key"]

TRADING_CLIENT = TradingClient(
    api_key, 
    secret_key,
    paper=isPaper
)
STOCK_HISTORIC_DATA_CLIENT = StockHistoricalDataClient(
    api_key, 
    secret_key
)
STOCK_LIVE_DATA_STREAM = StockDataStream(
    api_key, 
    secret_key
)
OPTION_HISTORIC_DATA_CLIENT = OptionHistoricalDataClient(
    api_key, 
    secret_key
)

CRYPTO_LIVE_DATA_STREAM = CryptoDataStream(
    api_key,
    secret_key
)
# Crypto clients don't need credentials (free tier)
CRYPTO_HISTORIC_DATA_CLIENT = CryptoHistoricalDataClient()
