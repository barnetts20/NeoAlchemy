import logging
import os
from project_context import PROJECT_ROOT

LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("alchemy")
logger.setLevel(logging.INFO)

if not logger.hasHandlers():
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(ch)

    # File handler
    fh = logging.FileHandler(os.path.join(LOG_DIR, "alchemy.log"))
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(fh)

# Optional: disable propagation to root logger to avoid duplicate logs
logger.propagate = False
