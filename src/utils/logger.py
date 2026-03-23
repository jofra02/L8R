import logging
import sys
import os
from logging.handlers import RotatingFileHandler
from src.config import settings

_initialized = False

def setup_logging():
    """Configure the root logger with console + rotating file output."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Ensure log directory exists
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), settings.LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(log_format))

    # Rotating file handler — 10 MB per file, keep 5 backups
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "agent.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(log_format))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    # Quiet noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance."""
    return logging.getLogger(name)
