"""Integration tests for the full Matrix to PostgreSQL pipeline."""

import os
import asyncio
from nio.responses import LoginError, LoginResponse
import pytest
from nio import AsyncClient, RoomVisibility
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from matrix_influx.config import Settings
from matrix_influx.matrix_to_influx import MatrixInfluxBridge
from matrix_influx.schema import Message


@pytest.fixture
async def matrix_client(synapse_container) -> AsyncClient:
    """Create and configure a Matrix client."""
    client = AsyncClient(
        homeserver=synapse_container["homeserver"], user=synapse_container["user"]
    )

    # Login
    response: LoginResponse | LoginError = await client.login(
        password=synapse_container["password"]
    )
    assert response.access_token is not None

    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
def integration_settings(postgres_container, synapse_container, temp_dir) -> Settings:
    """Create settings for integration tests."""
    os.environ.update(
        {
            "MATRIX_HOMESERVER": synapse_container["homeserver"],
            "MATRIX_USER": synapse_container["user"],
            "MATRIX_PASSWORD": synapse_container["password"],
            "MATRIX_ROOM_ID": synapse_container["room_id"],
            "POSTGRES_URL": postgres_container["url"],
            "POSTGRES_STORE_CONTENT": "true",
        }
    )

    settings = Settings()
    settings.sync_state_file = str(temp_dir / "integration_sync_state.json")
    settings.logging.file_path = str(temp_dir / "integration.log")
    return settings


async def test_message_ingestion(
    integration_settings: Settings, matrix_client: AsyncClient, postgres_container: dict
):
    """Test the full pipeline of message ingestion."""
    # Create test rooms
    room_responses = []
    for i in range(2):
        room_response = await matrix_client.room_create(
            visibility=RoomVisibility.public, name=f"Test Room {i + 1}"
        )
        assert room_response.room_id is not None
        room_responses.append(room_response.room_id)

    # Update settings with room IDs
    integration_settings.matrix.room_ids = room_responses

    # Create and start the bridge
    bridge = MatrixInfluxBridge(integration_settings)
    await bridge.connect_to_matrix()

    # Send test messages to each room
    test_messages = {
        room_id: [
            f"Test message 1 in {room_id}",
            f"Test message 2 with #tag in {room_id}",
            f"Test message 3 with @mention in {room_id}",
        ]
        for room_id in room_responses
    }

    for room_id, messages in test_messages.items():
        for msg in messages:
            await matrix_client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": msg},
            )

    # Wait for messages to be processed
    await asyncio.sleep(2)

    # Fetch historical messages
    await bridge.fetch_historical_messages()

    # Verify messages in PostgreSQL
    engine = create_engine(integration_settings.postgres.url)
    with Session(engine) as session:
        for room_id, messages in test_messages.items():
            for msg in messages:
                stmt = select(Message).where(
                    Message.room_id == room_id, Message.content == msg
                )
                result = session.execute(stmt).scalar_one_or_none()
                assert result is not None
                assert result.content == msg
                assert result.room_id == room_id
                assert result.message_type == "m.text"


async def test_multi_room_sync_state(
    integration_settings: Settings, matrix_client: AsyncClient
):
    """Test sync state persistence across multiple rooms."""
    # Create multiple test rooms
    room_responses = []
    room_ids = set()
    for i in range(3):
        room_response = await matrix_client.room_create(
            visibility=RoomVisibility.public, name=f"Test Room {i + 1}"
        )
        assert room_response.room_id is not None
        room_ids |= {room_response.room_id}
        room_responses.append(room_response.room_id)

    # Configure bridge to monitor all rooms
    integration_settings.matrix.room_ids = list(
        room_ids
    )  # Empty list means monitor all rooms

    # First bridge instance
    bridge1 = MatrixInfluxBridge(integration_settings)
    await bridge1.connect_to_matrix()

    # Send messages to different rooms
    for room_id in room_ids:
        await matrix_client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": f"Initial message in {room_id}"},
        )

    # Let messages be processed
    await asyncio.sleep(10)
    await bridge1.fetch_historical_messages()

    # Store sync times
    original_sync_times = bridge1.room_sync_times.copy()
    assert all(ts is not None for ts in original_sync_times.values())

    # Verify messages in PostgreSQL
    with Session(bridge1.engine) as session:
        stmt = select(Message).order_by(Message.timestamp)
        initial_messages = session.execute(stmt).scalars().all()
        assert len(initial_messages) == len(room_ids)

    # Wait for some time to pass so the sync times are different
    await asyncio.sleep(3)

    # Create new bridge instance
    bridge2 = MatrixInfluxBridge(integration_settings)
    await bridge2.connect_to_matrix()
    bridge2.load_sync_state()

    # Verify sync states were restored
    assert bridge2.room_sync_times == original_sync_times

    # Send new messages to each room
    for room_id in room_ids:
        await matrix_client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": f"New message in {room_id}"},
        )

    # Let messages be processed
    await asyncio.sleep(10)

    # Verify only new messages are fetched
    await bridge2.fetch_historical_messages()
    for room_id in room_ids:
        assert bridge2.room_sync_times[room_id] > original_sync_times[room_id]

    # Verify new messages in PostgreSQL
    with Session(bridge2.engine) as session:
        stmt = select(Message).order_by(Message.timestamp)
        all_messages = session.execute(stmt).scalars().all()
        assert len(all_messages) == len(room_ids) * 2  # Initial + new messages


async def test_room_filtering(
    integration_settings: Settings, matrix_client: AsyncClient
):
    """Test that room filtering works correctly."""
    # Create multiple test rooms
    room_ids = []
    for i in range(3):
        room_response = await matrix_client.room_create(
            visibility=RoomVisibility.public, name=f"Test Room {i}"
        )
        assert room_response.room_id is not None
        room_ids.append(room_response.room_id)

    # Configure bridge to monitor only specific rooms
    monitored_rooms = room_ids[:2]  # Monitor only first two rooms
    integration_settings.matrix.room_ids = monitored_rooms

    bridge = MatrixInfluxBridge(integration_settings)
    await bridge.connect_to_matrix()

    # Send messages to all rooms
    for room_id in room_ids:
        await matrix_client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": f"Test message in {room_id}"},
        )

    await asyncio.sleep(2)
    await bridge.fetch_historical_messages()

    # Verify only monitored rooms have sync times
    for room_id in monitored_rooms:
        assert room_id in bridge.room_sync_times
        assert bridge.room_sync_times[room_id] is not None

    # Verify unmonitored room is not tracked
    unmonitored_room = room_ids[2]
    assert unmonitored_room not in bridge.room_sync_times
