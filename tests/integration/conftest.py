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
    
    # Generate initial configuration using migrate_config
    client.containers.run(
        "matrixdotorg/synapse:latest",
        "migrate_config",
        remove=True,
        environment={
            "SYNAPSE_SERVER_NAME": "test.local",
            "SYNAPSE_REPORT_STATS": "no",
            "SYNAPSE_ENABLE_REGISTRATION": "yes",
            "SYNAPSE_NO_TLS": "yes",
            "SYNAPSE_LOG_LEVEL": "INFO"
        },
        volumes={
            str(data_dir.absolute()): {'bind': '/data', 'mode': 'rw'}
        }
    )
    
    # Start Synapse with the generated config
    container = client.containers.run(
        "matrixdotorg/synapse:latest",
        detach=True,
        remove=True,
        environment={
            "SYNAPSE_LOG_LEVEL": "INFO"
        },
        volumes={
            str(data_dir.absolute()): {'bind': '/data', 'mode': 'rw'}
        },
        ports={'8008/tcp': 8008}
    )
    
    # Wait for Synapse to be ready
    max_retries = 30
    retry_interval = 1
    for _ in range(max_retries):
        try:
            logs = container.logs().decode('utf-8')
            if "Synapse now listening on port 8008" in logs:
                break
        except Exception:
            pass
        time.sleep(retry_interval)
    else:
        raise TimeoutError("Synapse failed to start within the expected time")
    
    # Create admin user
    container.exec_run(
        [
            "register_new_matrix_user",
            "-c", "/data/homeserver.yaml",
            "--admin",
            "-u", "admin",
            "-p", "admin_password",
            "http://localhost:8008"
        ]
    )
    
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
