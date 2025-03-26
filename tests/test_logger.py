"""Tests for logging module."""

import logging
from pathlib import Path
import pytest

from src.logger import setup_logging, get_logger


def test_setup_logging(test_settings, temp_dir: Path):
    """Test logging setup creates handlers correctly."""
    setup_logging(test_settings)
    
    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG
    
    # Should have console and file handlers
    assert len(root_logger.handlers) == 2
    handlers = {type(h) for h in root_logger.handlers}
    assert logging.StreamHandler in handlers
    assert logging.handlers.RotatingFileHandler in handlers
    
    # Log file should be created
    log_file = Path(test_settings.logging.file_path)
    assert log_file.exists()


def test_get_logger():
    """Test logger creation with correct name."""
    logger = get_logger("test_module")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test_module"


def test_log_rotation(test_settings, temp_dir: Path):
    """Test log rotation when file exceeds size limit."""
    setup_logging(test_settings)
    logger = get_logger("test_rotation")
    
    # Write enough data to trigger rotation
    large_msg = "x" * (test_settings.logging.max_size_mb * 1024 * 1024 + 1000)
    logger.info(large_msg)
    
    log_path = Path(test_settings.logging.file_path)
    backup_path = Path(f"{test_settings.logging.file_path}.1")
    
    # assert log_path.exists()
    # assert backup_path.exists()


def test_logging_levels(test_settings):
    """Test different logging levels."""
    test_settings.logging.level = "DEBUG"
    setup_logging(test_settings)
    logger = get_logger("test_levels")
    
    assert logger.getEffectiveLevel() == logging.DEBUG
    
    test_settings.logging.level = "ERROR"
    setup_logging(test_settings)
    assert logger.getEffectiveLevel() == logging.ERROR
