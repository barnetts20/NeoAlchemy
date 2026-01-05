import os
import sys
# Adds the project root to sys.path - enables absolute imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path: sys.path.append(PROJECT_ROOT)

from datetime import datetime
from alpaca.data import StockBarsRequest, CryptoBarsRequest;
from utils.logger import logger
from alpaca.data.timeframe import TimeFrame
from project_context import TRADING_CLIENT, STOCK_HISTORIC_DATA_CLIENT, CRYPTO_HISTORIC_DATA_CLIENT

def get_account_data():
    account_data = TRADING_CLIENT.get_account()
    logger.info("GET ACCOUNT DATA: " + account_data.model_dump_json())
    return account_data

def hist_sample():
    # request = StockBarsRequest(
    #     symbol_or_symbols="AAPL",
    #     timeframe=TimeFrame.Hour,
    #     adjustment="all",
    #     start=datetime(2020, 1, 1),
    #     limit=1000
    # )
    request = CryptoBarsRequest(
        symbol_or_symbols="BTC/USD",
        timeframe=TimeFrame.Hour,
        adjustment="all",
        start=datetime(2020, 1, 1),
        limit=1000
    )
    # data = STOCK_HISTORIC_DATA_CLIENT.get_stock_bars(request)
    data = CRYPTO_HISTORIC_DATA_CLIENT.get_crypto_bars(request)
    logger.info("GET HIST DATA: " + data.model_dump_json())
    return data

hist_sample()