# alpaca_account.py
import os
import sys

# Adds the project root to sys.path - enables absolute imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path: sys.path.append(PROJECT_ROOT)

from project_context import SECRETS, SETTINGS
from brokers.alpaca_constants import PAPER_API_URL_PREFIX, LIVE_API_URL_PREFIX

def get_auth_headers():
    """Return Alpaca API headers for requests, using global settings."""
    if SETTINGS["paper"]:
        key = "alpaca-paper"
    else:
        key = "alpaca"
    return {
        "APCA-API-KEY-ID": SECRETS[key]["api_key"],
        "APCA-API-SECRET-KEY": SECRETS[key]["secret_key"],
        "accept": "application/json"
    }

def get_url_prefix():
    """Return Alpaca URL prefix for requests, using global settings."""
    if SETTINGS["paper"]:
        return PAPER_API_URL_PREFIX
    else:
        return LIVE_API_URL_PREFIX
    
def get_url(ENDPOINT):
    return get_url_prefix() + ENDPOINT