"""Tests for Matrix to InfluxDB bridge."""

import json
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock
from pytest_mock import MockerFixture
from nio import (
    RoomMessageText, RoomMessagesResponse, RoomMessage,
    RoomMessageEmote, RoomMessageNotice, JoinedRoomsResponse
)
from influxdb_client import Point

from src.matrix_to_influx import MatrixInfluxBridge


@pytest.fixture
def bridge(test_settings, mocker: MockerFixture):
    """Create a test bridge instance with mocked clients."""
    # Create bridge instance
    bridge = MatrixInfluxBridge(test_settings)
    
    # Mock Matrix client
    mock_matrix = mocker.patch('nio.AsyncClient', autospec=True)
    mock_matrix_instance = mock_matrix.return_value
    mock_matrix_instance.joined_rooms = AsyncMock(return_value=JoinedRoomsResponse(
        rooms=["!test1:matrix.org", "!test2:matrix.org"]
    ))
    
    # Mock InfluxDB write_api directly
    mock_write_api = mocker.MagicMock()
    mock_write_api.write = mocker.MagicMock()
    bridge.write_api = mock_write_api
    
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
                "origin_server_ts": timestamp
            },
            body="test message",
            formatted_body="<p>test message</p>",
            format="org.matrix.custom.html",
        ),
        RoomMessageEmote(
            source={
                "event_id": "!test1:matrix.org",
                "sender": "@test2:matrix.org",
                "origin_server_ts": timestamp + 1000
            },
            body="waves hello",
            formatted_body="<em>waves hello</em>",
            format="org.matrix.custom.html",
        ),
        RoomMessageText(
            source={
                "event_id": "!test1:matrix.org",
                "sender": "@test3:matrix.org",
                "origin_server_ts": timestamp + 1500
            },
            body="test message 2",
            formatted_body="<p>test message 2</p>",
            format="org.matrix.custom.html",
        ),
        RoomMessageText(
            source={
                "event_id": "!test1:matrix.org",
                "sender": "@test4:matrix.org",
                "origin_server_ts": timestamp + 2000
            },
            body="test message 3",
            formatted_body="<p>test message 3</p>",
            format="org.matrix.custom.html",
        ),
        RoomMessageNotice(
            source={
                "event_id": "!test1:matrix.org",
                "sender": "@system:matrix.org",
                "origin_server_ts": timestamp + 2000
            },
            body="System notice",
            formatted_body="<strong>System notice</strong>",
            format="org.matrix.custom.html",
        )
    ]


def test_load_sync_state(bridge, temp_dir):
    """Test loading sync state from file."""
    # Test with existing state file
    timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    test_state = {
        "!test1:matrix.org": timestamp,
        "!test2:matrix.org": timestamp + 1000
    }
    with open(bridge.settings.sync_state_file, 'w') as f:
        json.dump(test_state, f)
    
    bridge.load_sync_state()
    assert bridge.room_sync_times == test_state
    
    # Test with missing state file
    import os
    os.remove(bridge.settings.sync_state_file)
    bridge.load_sync_state()
    assert not bridge.room_sync_times
    
    # Test with corrupted state file
    with open(bridge.settings.sync_state_file, 'w') as f:
        f.write("invalid json")
    
    bridge.load_sync_state()
    assert not bridge.room_sync_times


def test_save_sync_state(bridge):
    """Test saving sync state to file."""
    timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    test_state = {
        "!test1:matrix.org": timestamp,
        "!test2:matrix.org": timestamp + 1000
    }
    bridge.room_sync_times = test_state.copy()
    bridge.save_sync_state()
    
    with open(bridge.settings.sync_state_file, 'r') as f:
        state = json.load(f)
        assert state == test_state


async def test_fetch_historical_messages(bridge, mock_messages):
    """Test fetching historical messages from multiple rooms."""
    # Set up mock response for each room
    mock_response = RoomMessagesResponse(
        chunk=mock_messages,
        start="t1",
        end="t2",
        room_id="!test1:matrix.org"
    )
    bridge.matrix_client.room_messages = AsyncMock(return_value=mock_response)
    
    # Initialize monitored rooms
    bridge.monitored_rooms = {"!test1:matrix.org", "!test2:matrix.org"}
    bridge.room_sync_times = {
        "!test1:matrix.org": None,
        "!test2:matrix.org": None
    }
    
    await bridge.fetch_historical_messages()
    
    # Verify messages were written to InfluxDB for each room
    text_message_count = sum(1 for msg in mock_messages if isinstance(msg, RoomMessageText))
    expected_calls = text_message_count * len(bridge.monitored_rooms)
    assert bridge.write_api.write.call_count == expected_calls
    
    # Verify sync times were updated for both rooms
    last_message_time = mock_messages[-1].source["origin_server_ts"]
    for room_id in bridge.monitored_rooms:
        assert bridge.room_sync_times[room_id] == last_message_time


async def test_message_type_handling(bridge, mock_messages):
    """Test handling of different message types."""
    mock_response = RoomMessagesResponse(
        chunk=mock_messages,
        start="t1",
        end="t2",
        room_id="!test1:matrix.org"
    )
    bridge.matrix_client.room_messages = AsyncMock(return_value=mock_response)
    
    # Initialize monitored rooms
    bridge.monitored_rooms = {"!test1:matrix.org"}
    bridge.room_sync_times = {"!test1:matrix.org": None}
    
    await bridge.fetch_historical_messages()
    
    points = [call.kwargs['record'] for call in bridge.write_api.write.call_args_list]
    text_messages = [msg for msg in mock_messages if isinstance(msg, RoomMessageText)]
    
    # Verify we have the right number of points
    assert len(points) == len(text_messages)
    
    # Verify message types were properly tagged
    for point, msg in zip(points, text_messages):
        assert isinstance(point, Point)
        assert point._tags["message_type"] == "RoomMessageText"
        assert point._tags["sender"] == msg.source["sender"]
        assert point._tags["room_id"] == "!test1:matrix.org"
        assert point._fields["content"] == msg.body


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
        chunk=[RoomMessageText(
            source={
                "event_id": "!test1:matrix.org",
                "sender": "@test:matrix.org",
                "origin_server_ts": int(datetime.now(timezone.utc).timestamp() * 1000)
            },
            body="test",
            formatted_body="<p>test</p>",
            format="org.matrix.custom.html",
        )],
        start="t1",
        end="t2"
    )
    
    bridge.write_api.write.side_effect = Exception("Write Error")
    
    with pytest.raises(Exception, match="Write Error"):
        await bridge.fetch_historical_messages()


class MockLoginResponse:
    """Mock Matrix login response."""
    @property
    def access_token(self):
        return "mock_token"
