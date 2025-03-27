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
def test_settings(temp_dir: Path, postgres_container) -> Settings:
    """Create test settings with mock values."""
    os.environ.update({
        'MATRIX_HOMESERVER': 'https://test.matrix.org',
        'MATRIX_USER': '@test:matrix.org',
        'MATRIX_PASSWORD': 'test_password',
        'MATRIX_ROOM_IDS': '!test1:matrix.org,!test2:matrix.org',
        'POSTGRES_URL': postgres_container["url"],
        'POSTGRES_STORE_CONTENT': 'true',
    })
    
    settings = Settings()
    settings.sync_state_file = str(temp_dir / "test_sync_state.json")
    settings.logging.file_path = str(temp_dir / "test.log")
    return settings


@pytest.fixture
def mock_matrix_client(mocker: MockerFixture):
    """Create a mock Matrix client."""
    return mocker.patch('nio.AsyncClient', autospec=True)


@pytest.fixture(scope="session")
def postgres_container(docker_ip, docker_services):
    """Create a PostgreSQL container for integration tests."""
    port = docker_services.port_for("postgres", 5432)
    url = f"postgresql://test:test123@{docker_ip}:{port}/matrix_messages"
    docker_services.wait_until_responsive(
        timeout=30.0, pause=0.1,
        check=lambda: docker_services.port_for("postgres", 5432) is not None
    )
    return {
        "host": docker_ip,
        "port": port,
        "database": "matrix_messages",
        "user": "test",
        "password": "test123",
        "url": url
    }


@pytest.fixture(scope="session")
def synapse_container(docker_ip, docker_services):
    """Create a Synapse container for integration tests."""
    port = docker_services.port_for("synapse", 8008)
    homeserver = f"http://{docker_ip}:{port}"
    docker_services.wait_until_responsive(
        timeout=30.0, pause=0.1,
        check=lambda: docker_services.port_for("synapse", 8008) is not None
    )
    return {
        "homeserver": homeserver,
        "user": "@test:test.matrix.org",
        "password": "test123",
        "room_id": "!test:test.matrix.org"
    }
