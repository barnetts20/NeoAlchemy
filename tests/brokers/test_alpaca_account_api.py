import os
import sys
# Adds the project root to sys.path - enables absolute imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path: sys.path.append(PROJECT_ROOT)

from brokers.alpaca_account_api import get_account_data
from utils.logger import logger

def test_get_account_data():
    response = get_account_data()
    assert response.status_code == 200
    data = response.json()
    assert "cash" in data
    assert "equity" in data
    logger.info("Account data test passed.")
    

    