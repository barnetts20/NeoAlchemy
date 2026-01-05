import os
import sys
# Adds the project root to sys.path - enables absolute imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path: sys.path.append(PROJECT_ROOT)

import requests
from utils.logger import logger
from brokers.alpaca_url import get_auth_headers, get_url
from brokers.alpaca_constants import ACCOUNT_ENDPOINT

def get_account_data():
    response = requests.get(get_url(ACCOUNT_ENDPOINT), headers=get_auth_headers())
    if response.status_code == 200:
        logger.info("Account info retrieved successfully!")
        logger.info(f"{response.json()}")
    else:
        logger.error(f"Error fetching account info: {response.status_code} {response.text}")
    return response

#get_account_data()