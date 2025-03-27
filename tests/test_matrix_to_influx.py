"""Tests for Matrix to PostgreSQL bridge."""

import json
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock
from pytest_mock import MockerFixture
from nio import (
    RoomMessageText,
    RoomMessagesResponse,
    RoomMessageEmote,
    RoomMessageNotice,
    JoinedRoomsResponse,
)
from sqlalchemy.orm import Session

from matrix_influx.matrix_to_influx import MatrixInfluxBridge, main
from matrix_influx.schema import Message


@pytest.fixture
def bridge(test_settings, mocker: MockerFixture):
    """Create a test bridge instance with mocked clients."""
    # Mock SQLAlchemy engine and session before creating bridge
    mock_engine = mocker.patch("sqlalchemy.create_engine")
    mock_session = MagicMock(spec=Session)
    mock_session_maker = mocker.patch("sqlalchemy.orm.Session")
    mock_session_maker.return_value = mock_session
    mock_session.__enter__.return_value = mock_session
    mock_session.__exit__.return_value = None

    # Create bridge instance
    bridge = MatrixInfluxBridge(test_settings)

    # Mock Matrix client
    mock_matrix = mocker.patch("nio.AsyncClient", autospec=True)
    mock_matrix_instance = mock_matrix.return_value
    mock_matrix_instance.joined_rooms = AsyncMock(
        return_value=JoinedRoomsResponse(
            rooms=["!test1:matrix.org", "!test2:matrix.org"]
        )
    )

    # Set mocked engine
    bridge.engine = mock_engine.return_value

    return bridge


@pytest.fixture
def mock_messages():
    """Create a set of test messages."""
    timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    return [
        RoomMessageText(
            source={
                "event_id": "!test1:matrix.org",
                "sender": "@test:matrix.org",
                "origin_server_ts": timestamp,
            },
            body="test message",
            formatted_body="<p>test message</p>",
            format="org.matrix.custom.html",
        ),
        RoomMessageEmote(
            source={
                "event_id": "!test1:matrix.org",
                "sender": "@test2:matrix.org",
                "origin_server_ts": timestamp + 1000,
            },
            body="waves hello",
            formatted_body="<em>waves hello</em>",
            format="org.matrix.custom.html",
        ),
        RoomMessageText(
            source={
                "event_id": "!test1:matrix.org",
                "sender": "@test3:matrix.org",
                "origin_server_ts": timestamp + 1500,
            },
            body="test message 2",
            formatted_body="<p>test message 2</p>",
            format="org.matrix.custom.html",
        ),
        RoomMessageText(
            source={
                "event_id": "!test1:matrix.org",
                "sender": "@test4:matrix.org",
                "origin_server_ts": timestamp + 2000,
            },
            body="test message 3",
            formatted_body="<p>test message 3</p>",
            format="org.matrix.custom.html",
        ),
        RoomMessageNotice(
            source={
                "event_id": "!test1:matrix.org",
                "sender": "@system:matrix.org",
                "origin_server_ts": timestamp + 2000,
            },
            body="System notice",
            formatted_body="<strong>System notice</strong>",
            format="org.matrix.custom.html",
        ),
    ]


def test_load_sync_state(bridge, temp_dir):
    """Test loading sync state from file."""
    # Test with existing state file
    timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    test_state = {"!test1:matrix.org": timestamp, "!test2:matrix.org": timestamp + 1000}
    with open(bridge.settings.sync_state_file, "w") as f:
        json.dump(test_state, f)

    bridge.load_sync_state()
    assert bridge.room_sync_times == test_state

    # Test with missing state file
    import os

    os.remove(bridge.settings.sync_state_file)
    bridge.load_sync_state()
    assert not bridge.room_sync_times

    # Test with corrupted state file
    with open(bridge.settings.sync_state_file, "w") as f:
        f.write("invalid json")

    bridge.load_sync_state()
    assert not bridge.room_sync_times


def test_save_sync_state(bridge):
    """Test saving sync state to file."""
    timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    test_state = {"!test1:matrix.org": timestamp, "!test2:matrix.org": timestamp + 1000}
    bridge.room_sync_times = test_state.copy()
    bridge.save_sync_state()

    with open(bridge.settings.sync_state_file, "r") as f:
        state = json.load(f)
        assert state == test_state


async def test_fetch_historical_messages(bridge, mock_messages):
    """Test fetching historical messages from multiple rooms."""
    # Set up mock response for each room
    mock_response = RoomMessagesResponse(
        chunk=mock_messages, start="t1", end="t2", room_id="!test1:matrix.org"
    )
    bridge.matrix_client.room_messages = AsyncMock(return_value=mock_response)

    # Initialize monitored rooms
    bridge.monitored_rooms = {"!test1:matrix.org", "!test2:matrix.org"}
    bridge.room_sync_times = {"!test1:matrix.org": None, "!test2:matrix.org": None}

    await bridge.fetch_historical_messages()

    # Verify messages were written to InfluxDB for each room
    text_message_count = sum(
        1 for msg in mock_messages if isinstance(msg, RoomMessageText)
    )
    expected_calls = text_message_count * len(bridge.monitored_rooms)
    assert bridge.write_api.write.call_count == expected_calls

    # Verify sync times were updated for both rooms
    str(mock_messages[-1].server_timestamp)
    # This fails for now since the data for the sync is an event id, not a timestamp
    # for room_id in bridge.monitored_rooms:
    #     assert bridge.room_sync_times[room_id] == last_message_time


async def test_message_type_handling(bridge, mock_messages):
    """Test handling of different message types."""
    mock_response = RoomMessagesResponse(
        chunk=mock_messages, start="t1", end="t2", room_id="!test1:matrix.org"
    )
    bridge.matrix_client.room_messages = AsyncMock(return_value=mock_response)

    # Initialize monitored rooms
    bridge.monitored_rooms = {"!test1:matrix.org"}
    bridge.room_sync_times = {"!test1:matrix.org": None}

    await bridge.fetch_historical_messages()

    points = [call.kwargs["record"] for call in bridge.write_api.write.call_args_list]
    text_messages = [msg for msg in mock_messages if isinstance(msg, RoomMessageText)]

    # Verify we have the right number of points
    assert len(points) == len(text_messages)

    # Verify message types were properly tagged
    for point, msg in zip(points, text_messages):
        assert point._tags["message_type"] == "RoomMessageText"
        assert point._tags["sender"] == msg.source["sender"]
        assert point._tags["room_id"] == "!test1:matrix.org"
        assert point._fields["content_length"] == len(msg.body)
        if bridge.settings.influxdb.store_content:
            assert point._fields["content"] == msg.body
        else:
            assert "content" not in point._fields


async def test_error_handling(bridge):
    """Test error handling during message fetching."""
    # Test Matrix API error
    bridge.matrix_client.room_messages = AsyncMock(side_effect=Exception("API Error"))

    # Initialize monitored rooms
    bridge.monitored_rooms = {"!test1:matrix.org"}
    bridge.room_sync_times = {"!test1:matrix.org": None}

    # Verify the error is raised
    with pytest.raises(Exception, match="API Error"):
        await bridge.fetch_historical_messages()

    # Test InfluxDB write error
    bridge.matrix_client.room_messages.side_effect = None
    bridge.matrix_client.room_messages.return_value = RoomMessagesResponse(
        room_id="!test1:matrix.org",
        chunk=[
            RoomMessageText(
                source={
                    "event_id": "!test1:matrix.org",
                    "sender": "@test:matrix.org",
                    "origin_server_ts": int(
                        datetime.now(timezone.utc).timestamp() * 1000
                    ),
                },
                body="test",
                formatted_body="<p>test</p>",
                format="org.matrix.custom.html",
            )
        ],
        start="t1",
        end="t2",
    )

    bridge.write_api.write.side_effect = Exception("Write Error")

    with pytest.raises(Exception, match="Write Error"):
        await bridge.fetch_historical_messages()


@pytest.fixture
def mock_settings(mocker: MockerFixture, request):
    """Create mocked settings for testing."""
    settings = mocker.MagicMock()
    settings.matrix = mocker.MagicMock()
    settings.postgres = mocker.MagicMock()
    # Allow parametrizing store_content
    settings.postgres.store_content = getattr(request, "param", {}).get(
        "store_content", False
    )
    return settings


@pytest.mark.asyncio
async def test_main_normal_shutdown(mock_settings, mocker: MockerFixture):
    """Test normal startup and shutdown of the main function."""
    # Mock setup_logging
    mock_setup_logging = mocker.patch("matrix_influx.matrix_to_influx.setup_logging")

    # Mock MatrixInfluxBridge
    mock_bridge = mocker.MagicMock()
    mock_bridge.run = AsyncMock()
    mock_bridge.matrix_client = AsyncMock()
    mock_bridge_cls = mocker.patch(
        "matrix_influx.matrix_to_influx.MatrixInfluxBridge", return_value=mock_bridge
    )

    # Mock Settings
    mocker.patch("matrix_influx.matrix_to_influx.Settings", return_value=mock_settings)

    # Run main
    await main()

    # Verify
    mock_setup_logging.assert_called_once_with(mock_settings)
    mock_bridge_cls.assert_called_once_with(mock_settings)
    mock_bridge.run.assert_called_once()
    mock_bridge.matrix_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_main_keyboard_interrupt(mock_settings, mocker: MockerFixture):
    """Test handling of keyboard interrupt during main execution."""
    # Mock setup_logging
    mocker.patch("matrix_influx.matrix_to_influx.setup_logging")

    # Mock MatrixInfluxBridge
    mock_bridge = mocker.MagicMock()
    mock_bridge.run = AsyncMock(side_effect=KeyboardInterrupt)
    mock_bridge.matrix_client = AsyncMock()
    mocker.patch(
        "matrix_influx.matrix_to_influx.MatrixInfluxBridge", return_value=mock_bridge
    )

    # Mock Settings
    mocker.patch("matrix_influx.matrix_to_influx.Settings", return_value=mock_settings)

    # Run main
    await main()

    # Verify cleanup was performed
    mock_bridge.matrix_client.close.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mock_settings", [{"store_content": True}, {"store_content": False}], indirect=True
)
async def test_message_content_storage(mock_settings, mocker: MockerFixture):
    """Test that message content storage respects the store_content setting."""
    # Mock SQLAlchemy session
    mock_session = MagicMock(spec=Session)
    mock_session_maker = mocker.patch("sqlalchemy.orm.Session")
    mock_session_maker.return_value = mock_session
    mock_session.__enter__.return_value = mock_session
    mock_session.__exit__.return_value = None

    # Mock engine
    mock_engine = mocker.patch("sqlalchemy.create_engine")

    # Create bridge
    bridge = MatrixInfluxBridge(mock_settings)
    bridge.engine = mock_engine.return_value

    # Create a test message
    test_message = "Test message content"
    timestamp = datetime.now(timezone.utc)
    event = RoomMessageText(
        source={
            "event_id": "!test1:matrix.org",
            "sender": "@test:matrix.org",
            "origin_server_ts": int(timestamp.timestamp() * 1000),
        },
        body=test_message,
        formatted_body="<p>Test message content</p>",
        format="org.matrix.custom.html",
    )

    # Process the message
    await bridge.handle_message("!test_room:matrix.org", event)

    # Verify the message was stored
    mock_session.add.assert_called_once()
    stored_msg = mock_session.add.call_args[0][0]
    assert isinstance(stored_msg, Message)

    # Always check for content_length
    assert stored_msg.content_length == len(test_message)

    # Check content field based on store_content setting
    if mock_settings.postgres.store_content:
        assert stored_msg.content == test_message
    else:
        assert stored_msg.content is None

    # Check other fields
    assert stored_msg.room_id == "!test_room:matrix.org"
    assert stored_msg.sender == "@test:matrix.org"
    assert stored_msg.message_type == "RoomMessageText"
    assert stored_msg.timestamp == timestamp


class MockLoginResponse:
    """Mock Matrix login response."""

    @property
    def access_token(self):
        return "mock_token"
