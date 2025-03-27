"""Tests for Matrix to PostgreSQL bridge."""

import json
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock
from pytest_mock import MockerFixture
from nio import (
    RoomMessageText,
    RoomMessageEmote,
    RoomMessageNotice,
    JoinedRoomsResponse,
)
from sqlalchemy.orm import Session

from matrix_influx.matrix_to_influx import MatrixInfluxBridge
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


def test_save_sync_state(bridge, temp_dir):
    """Test saving sync state to file."""
    timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    bridge.room_sync_times = {
        "!test1:matrix.org": timestamp,
        "!test2:matrix.org": timestamp + 1000,
    }

    bridge.save_sync_state()

    with open(bridge.settings.sync_state_file, "r") as f:
        loaded_state = json.load(f)

    assert loaded_state == bridge.room_sync_times


def test_message_type_handling(bridge, mock_messages):
    """Test handling of different message types."""
    for message in mock_messages:
        bridge.store_message_in_db(
            room_id="!test:matrix.org",
            sender=message.sender,
            message=message.body,
            timestamp=datetime.fromtimestamp(
                message.server_timestamp / 1000, tz=timezone.utc
            ),
            message_type=type(message).__name__,
        )

    # Verify each message was stored with correct type
    mock_session = Session.return_value
    assert mock_session.add.call_count == len(mock_messages)
    for i, message in enumerate(mock_messages):
        stored_msg = mock_session.add.call_args_list[i][0][0]
        assert isinstance(stored_msg, Message)
        assert stored_msg.message_type == type(message).__name__
        assert stored_msg.content_length == len(message.body)


@pytest.mark.parametrize(
    "mock_settings", [{"store_content": True}, {"store_content": False}], indirect=True
)
def test_message_content_storage(mock_settings, mocker: MockerFixture):
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

    # Test message
    test_message = "Test message content"
    timestamp = datetime.now(timezone.utc)

    # Store message
    bridge.store_message_in_db(
        room_id="!test:matrix.org",
        sender="@test:matrix.org",
        message=test_message,
        timestamp=timestamp,
        message_type="RoomMessageText",
    )

    # Verify message was stored correctly
    mock_session.add.assert_called_once()
    stored_msg = mock_session.add.call_args[0][0]

    # Always check content length
    assert stored_msg.content_length == len(test_message)

    # Check content based on store_content setting
    if mock_settings.postgres.store_content:
        assert stored_msg.content == test_message
    else:
        assert stored_msg.content is None

    # Check other fields
    assert stored_msg.room_id == "!test:matrix.org"
    assert stored_msg.sender == "@test:matrix.org"
    assert stored_msg.message_type == "RoomMessageText"
    assert stored_msg.timestamp == timestamp


class MockLoginResponse:
    """Mock Matrix login response."""

    @property
    def access_token(self):
        return "mock_token"
