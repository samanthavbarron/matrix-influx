"""Matrix to PostgreSQL bridge - A tool to archive Matrix chat messages into PostgreSQL."""

from importlib import metadata

__version__ = "0.1.0"
__author__ = "Codeium"
__license__ = "MIT"

try:
    __version__ = metadata.version(__package__ or __name__)
except metadata.PackageNotFoundError:
    # Package is not installed
    pass

from .config import Settings, MatrixConfig, PostgresConfig, LogConfig
from .logger import setup_logging, get_logger
from .matrix_to_influx import MatrixInfluxBridge

__all__ = [
    "Settings",
    "MatrixConfig",
    "PostgresConfig",
    "LogConfig",
    "setup_logging",
    "get_logger",
    "MatrixInfluxBridge",
]
