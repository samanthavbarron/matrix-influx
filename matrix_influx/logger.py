import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import Settings


def setup_logging(settings: Settings) -> None:
    """Configure logging with both file and console handlers"""
    # Create logs directory if it doesn't exist
    log_path = Path(settings.logging.file_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Create formatters and handlers
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # File handler with rotation
    file_handler = RotatingFileHandler(
        settings.logging.file_path,
        maxBytes=settings.logging.max_size_mb * 1024 * 1024,  # Convert MB to bytes
        backupCount=settings.logging.backup_count,
    )
    file_handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.logging.level.upper()))

    # Remove any existing handlers and add our new ones
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the specified name"""
    return logging.getLogger(name)
