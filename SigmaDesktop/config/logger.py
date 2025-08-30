# logger.py
import logging
import os
from datetime import datetime

# Create logs folder if not exists
if not os.path.exists("logs"):
    os.makedirs("logs")

# Log file with timestamp (daily log)
log_filename = datetime.now().strftime("logs/app_%Y-%m-%d.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("SigmaApp")
