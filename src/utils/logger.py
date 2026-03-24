import logging
import sys
import os
from logging.handlers import RotatingFileHandler
from src.config import settings

_FILE_HANDLER_NAME = "_agent_file_handler"


def setup_logging():
    """Configure the root logger with console + rotating file output.

    Safe to call multiple times — checks whether the file handler is
    already attached before adding it (survives uvicorn's dictConfig reset).
    """
    root = logging.getLogger()
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    root.setLevel(level)

    # Skip if our file handler is already attached
    if any(getattr(h, "name", None) == _FILE_HANDLER_NAME for h in root.handlers):
        return

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    # Ensure log directory exists (relative to project root)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_dir = os.path.join(project_root, settings.LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)

    # Console handler (only add if none exist yet — uvicorn provides its own)
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root.handlers):
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        root.addHandler(console)

    # Rotating file handler — 10 MB per file, keep 5 backups
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "agent.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.name = _FILE_HANDLER_NAME
    root.addHandler(file_handler)

    # Quiet noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance."""
    return logging.getLogger(name)
