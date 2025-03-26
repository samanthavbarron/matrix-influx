"""Common test fixtures for matrix-to-influx tests."""

import os
from pathlib import Path
import pytest
from pytest_mock import MockerFixture

from src.config import Settings


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for test files."""
    return tmp_path


@pytest.fixture
def test_settings(temp_dir: Path) -> Settings:
    """Create test settings with mock values."""
    os.environ.update({
        'MATRIX_HOMESERVER': 'https://test.matrix.org',
        'MATRIX_USER': '@test:matrix.org',
        'MATRIX_PASSWORD': 'test_password',
        'MATRIX_ROOM_IDS': '!test1:matrix.org,!test2:matrix.org',
        'INFLUXDB_URL': 'http://localhost:8086',
        'INFLUXDB_TOKEN': 'test_token',
        'INFLUXDB_ORG': 'test_org',
        'INFLUXDB_BUCKET': 'test_bucket',
    })
    
    settings = Settings()
    settings.sync_state_file = str(temp_dir / "test_sync_state.json")
    settings.logging.file_path = str(temp_dir / "test.log")
    return settings


@pytest.fixture
def mock_matrix_client(mocker: MockerFixture):
    """Create a mock Matrix client."""
    return mocker.patch('nio.AsyncClient', autospec=True)
