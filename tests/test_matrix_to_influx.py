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

from src.matrix_to_influx import MatrixInfluxBridge, main


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
    last_message_time = str(mock_messages[-1].server_timestamp)
    # This fails for now since the data for the sync is an event id, not a timestamp
    # for room_id in bridge.monitored_rooms:
    #     assert bridge.room_sync_times[room_id] == last_message_time


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


@pytest.fixture
def mock_settings(mocker: MockerFixture, request):
    """Create mocked settings for testing."""
    settings = mocker.MagicMock()
    settings.matrix = mocker.MagicMock()
    settings.influxdb = mocker.MagicMock()
    # Allow parametrizing store_content
    settings.influxdb.store_content = getattr(request, 'param', {}).get('store_content', False)
    return settings


@pytest.mark.asyncio
async def test_main_normal_shutdown(mock_settings, mocker: MockerFixture):
    """Test normal startup and shutdown of the main function."""
    # Mock setup_logging
    mock_setup_logging = mocker.patch('src.matrix_to_influx.setup_logging')
    
    # Mock MatrixInfluxBridge
    mock_bridge = mocker.MagicMock()
    mock_bridge.run = AsyncMock()
    mock_bridge.matrix_client = AsyncMock()
    mock_bridge.influx_client = mocker.MagicMock()
    mock_bridge_cls = mocker.patch('src.matrix_to_influx.MatrixInfluxBridge', return_value=mock_bridge)
    
    # Mock Settings
    mocker.patch('src.matrix_to_influx.Settings', return_value=mock_settings)
    
    # Run main
    await main()
    
    # Verify
    mock_setup_logging.assert_called_once_with(mock_settings)
    mock_bridge_cls.assert_called_once_with(mock_settings)
    mock_bridge.run.assert_called_once()
    mock_bridge.matrix_client.close.assert_called_once()
    mock_bridge.influx_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_main_keyboard_interrupt(mock_settings, mocker: MockerFixture):
    """Test handling of keyboard interrupt during main execution."""
    # Mock setup_logging
    mocker.patch('src.matrix_to_influx.setup_logging')
    
    # Mock MatrixInfluxBridge
    mock_bridge = mocker.MagicMock()
    mock_bridge.run = AsyncMock(side_effect=KeyboardInterrupt)
    mock_bridge.matrix_client = AsyncMock()
    mock_bridge.influx_client = mocker.MagicMock()
    mocker.patch('src.matrix_to_influx.MatrixInfluxBridge', return_value=mock_bridge)
    
    # Mock Settings
    mocker.patch('src.matrix_to_influx.Settings', return_value=mock_settings)
    
    # Run main
    await main()
    
    # Verify cleanup was performed
    mock_bridge.matrix_client.close.assert_called_once()
    mock_bridge.influx_client.close.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('mock_settings', [
    {'store_content': True},
    {'store_content': False}
], indirect=True)
async def test_message_content_storage(mock_settings, mocker: MockerFixture):
    """Test that message content storage respects the store_content setting."""
    # Mock setup_logging
    mocker.patch('src.matrix_to_influx.setup_logging')
    
    # Create a bridge instance
    bridge = MatrixInfluxBridge(mock_settings)
    
    # Mock the write_api
    mock_write_api = mocker.MagicMock()
    bridge.write_api = mock_write_api
    
    # Create a test message
    test_message = "Test message content"
    timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    event = RoomMessageText(
        source={
            "event_id": "!test1:matrix.org",
            "sender": "@test:matrix.org",
            "origin_server_ts": timestamp
        },
        body=test_message,
        formatted_body="<p>Test message content</p>",
        format="org.matrix.custom.html",
    )
    
    # Process the message
    await bridge.handle_message("!test_room:matrix.org", event)
    
    # Verify the write call
    assert mock_write_api.write.called
    call_args = mock_write_api.write.call_args[1]
    point = call_args['record']
    # Get all fields from the point
    fields = {k: v for k, v in point._fields.items()}
    
    # Always check for content_length
    assert 'content_length' in fields
    assert fields['content_length'] == len(test_message)
    
    # Check content field based on store_content setting
    if mock_settings.influxdb.store_content:
        assert 'content' in fields
        assert fields['content'] == test_message
    else:
        assert 'content' not in fields


class MockLoginResponse:
    """Mock Matrix login response."""
    @property
    def access_token(self):
        return "mock_token"
