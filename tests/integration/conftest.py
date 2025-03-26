"""Fixtures for integration tests."""

import os
import pytest
import docker
from pathlib import Path
from typing import Generator
import time

@pytest.fixture(scope="session")
def influxdb_container() -> Generator[dict, None, None]:
    """Start InfluxDB container for integration tests."""
    client = docker.from_env()
    
    # Pull and start InfluxDB container
    container = client.containers.run(
        "influxdb:2.7",
        detach=True,
        remove=True,
        environment={
            "DOCKER_INFLUXDB_INIT_MODE": "setup",
            "DOCKER_INFLUXDB_INIT_USERNAME": "test_user",
            "DOCKER_INFLUXDB_INIT_PASSWORD": "test_password",
            "DOCKER_INFLUXDB_INIT_ORG": "test_org",
            "DOCKER_INFLUXDB_INIT_BUCKET": "test_bucket",
            "DOCKER_INFLUXDB_INIT_ADMIN_TOKEN": "test_token",
        },
        ports={'8086/tcp': 8086}
    )
    
    # Wait for InfluxDB to be ready
    time.sleep(5)
    
    try:
        yield {
            "url": "http://localhost:8086",
            "token": "test_token",
            "org": "test_org",
            "bucket": "test_bucket"
        }
    finally:
        container.stop()


@pytest.fixture(scope="session")
def synapse_container() -> Generator[dict, None, None]:
    """Start Synapse container for integration tests."""
    client = docker.from_env()
    
    # Create temporary directory for Synapse data
    data_dir = Path("./synapse-data")
    data_dir.mkdir(exist_ok=True)
    
    # Generate config
    client.containers.run(
        "matrixdotorg/synapse:latest",
        "generate",
        remove=True,
        environment={
            "SYNAPSE_SERVER_NAME": "test.local",
            "SYNAPSE_REPORT_STATS": "no"
        },
        volumes={
            str(data_dir.absolute()): {'bind': '/data', 'mode': 'rw'}
        }
    )
    
    # Start Synapse
    container = client.containers.run(
        "matrixdotorg/synapse:latest",
        detach=True,
        remove=True,
        environment={
            "SYNAPSE_SERVER_NAME": "test.local",
            "SYNAPSE_REPORT_STATS": "no"
        },
        volumes={
            str(data_dir.absolute()): {'bind': '/data', 'mode': 'rw'}
        },
        ports={'8008/tcp': 8008}
    )
    
    # Wait for Synapse to be ready
    time.sleep(10)
    
    try:
        yield {
            "homeserver": "http://localhost:8008",
            "user": "@admin:test.local",
            "password": "admin_password",
            "room_id": "!test:test.local"
        }
    finally:
        container.stop()
        # Clean up data directory
        for file in data_dir.glob("*"):
            file.unlink()
        data_dir.rmdir()
