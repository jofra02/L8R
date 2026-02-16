import logging
import sys
from src.config import settings

def setup_logging():
    """Configure the root logger."""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set lower level for third-party libs if needed
    logging.getLogger("httpx").setLevel(logging.WARNING)

def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance."""
    return logging.getLogger(name)

# Initialize on import (optional, or call explicitly in main)
setup_logging()
