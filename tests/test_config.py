"""Tests for configuration module."""

import os
import pytest
from pydantic import ValidationError

from src.config import Settings, MatrixConfig, PostgresConfig, LogConfig


def test_matrix_config_validation():
    """Test MatrixConfig validation."""
    # Valid config with specific rooms
    config = MatrixConfig(
        homeserver="https://matrix.org",
        user="@test:matrix.org",
        password="password",
        room_ids=["!test:matrix.org", "!test2:matrix.org"]
    )
    assert config.homeserver == "https://matrix.org"
    assert config.user == "@test:matrix.org"
    assert len(config.room_ids) == 2
    
    # Valid config with no rooms (monitor all)
    config = MatrixConfig(
        homeserver="https://matrix.org",
        user="@test:matrix.org",
        password="password"
    )
    assert len(config.room_ids) == 0  # Empty list means monitor all rooms
    
    # Invalid config (missing required fields)
    with pytest.raises(ValidationError):
        MatrixConfig()


def test_postgres_config_validation():
    """Test PostgresConfig validation."""
    # Valid config
    config = PostgresConfig(
        host="0.0.0.0",
        port=5432,
        database="matrix_messages",
        user="test",
        password="test123",
        store_content=True
    )
    assert config.host == "0.0.0.0"
    assert config.port == 5432
    assert config.database == "matrix_messages"
    assert config.user == "test"
    assert config.password == "test123"
    assert config.store_content is True
    assert config.url == "postgresql://test:test123@0.0.0.0:5432/matrix_messages"
    
    # Invalid config (missing required fields)
    with pytest.raises(ValidationError):
        PostgresConfig()


def test_log_config_defaults():
    """Test LogConfig default values."""
    config = LogConfig()
    assert config.file_path == "logs/matrix_influx.log"
    assert config.max_size_mb == 10
    assert config.backup_count == 5
    assert config.level == "INFO"


def test_settings_from_env(test_settings: Settings):
    """Test Settings loads correctly from environment variables."""
    assert test_settings.matrix.homeserver == "https://test.matrix.org"
    assert test_settings.matrix.user == "@test:matrix.org"
    assert test_settings.postgres.host == "localhost"
    assert test_settings.postgres.port == 5432
    assert test_settings.postgres.database == "matrix_messages"
    assert test_settings.postgres.user == "test"
    assert test_settings.postgres.password == "test123"
    assert test_settings.postgres.store_content is True
    assert len(test_settings.matrix.room_ids) == 2
    assert "!test1:matrix.org" in test_settings.matrix.room_ids
    assert "!test2:matrix.org" in test_settings.matrix.room_ids


def test_settings_nested_env_vars():
    """Test Settings handles nested environment variables."""
    os.environ.update({
        "LOGGING__LEVEL": "DEBUG",
        "LOGGING__MAX_SIZE_MB": "20",
        "MATRIX_ROOM_IDS": ""  # Empty string means monitor all rooms
    })
    
    settings = Settings()
    assert settings.logging.level == "DEBUG"
    assert settings.logging.max_size_mb == 20
    assert len(settings.matrix.room_ids) == 0  # Should be empty list for monitoring all rooms
