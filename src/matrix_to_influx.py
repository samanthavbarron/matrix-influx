import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List, Set
from pathlib import Path
from nio import (
    AsyncClient, RoomMessageText, Response, LoginResponse,
    MatrixRoom, Event, RoomMessagesResponse, MessageDirection,
    RoomMember, RoomMemberEvent, JoinedRoomsResponse
)
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS, WriteApi

from config import Settings
from logger import setup_logging, get_logger

# Create logger for this module
logger = get_logger(__name__)

class MatrixInfluxBridge:
    def __init__(self, settings: Settings) -> None:
        self.settings: Settings = settings
        self.matrix_client: AsyncClient = AsyncClient(settings.matrix.homeserver, settings.matrix.user)
        self.influx_client: InfluxDBClient = InfluxDBClient(
            url=settings.influxdb.url,
            token=settings.influxdb.token,
            org=settings.influxdb.org
        )
        self.write_api: WriteApi = self.influx_client.write_api(write_options=SYNCHRONOUS)
        self.room_sync_times: Dict[str, Optional[int]] = {}
        self.monitored_rooms: Set[str] = set()
        self.load_sync_state()

    def load_sync_state(self) -> None:
        """Load the last sync timestamp for each room from file"""
        try:
            with open(self.settings.sync_state_file, 'r') as f:
                state = json.load(f)
                self.room_sync_times = {room: ts for room, ts in state.items()}
                for room_id, timestamp in self.room_sync_times.items():
                    time_str = datetime.fromtimestamp(timestamp / 1000) if timestamp else 'Never'
                    logger.info(f"Room {room_id} last sync time: {time_str}")
        except FileNotFoundError:
            logger.info("No previous sync state found")
            self.room_sync_times = {}
        except json.JSONDecodeError:
            logger.warning("Corrupted sync state file found, starting fresh")
            self.room_sync_times = {}

    def save_sync_state(self) -> None:
        """Save the current sync timestamp for each room to file"""
        with open(self.settings.sync_state_file, 'w') as f:
            json.dump(self.room_sync_times, f)

    async def connect_to_matrix(self) -> None:
        """Connect to Matrix server and join the specified room"""
        logger.info(f"Logging in to Matrix as {self.settings.matrix.user}...")
        response: LoginResponse = await self.matrix_client.login(password=self.settings.matrix.password)
        if not response.transport_response.ok:
            logger.error(f"Failed to log in with status code: {response.transport_response.status}")
            raise Exception(f"Failed to log in: {response.transport_response.status}")
        logger.info("Successfully logged in")

    def store_message_in_influx(self, room_id: str, sender: str, message: str, timestamp: datetime) -> None:
        """Store a Matrix message in InfluxDB"""
        point: Point = Point("matrix_messages") \
            .tag("room_id", room_id) \
            .tag("sender", sender) \
            .field("message", message) \
            .time(timestamp)

        self.write_api.write(bucket=self.settings.influxdb.bucket, record=point)

    async def message_callback(self, room: MatrixRoom, event: Event) -> None:
        """Callback for new messages"""
        if isinstance(event, RoomMessageText):
            logger.debug(f"New message in {room.room_id} from {event.sender}: {event.body}")
            await self.handle_message(room.room_id, event)
            
            # Update sync state with the latest message timestamp
            self.last_sync_time = max(event.server_timestamp, self.last_sync_time or 0)
            self.save_sync_state()

    async def fetch_historical_messages(self) -> None:
        """Fetch messages from all monitored rooms since their last sync time"""
        for room_id in self.monitored_rooms:
            last_sync = self.room_sync_times.get(room_id)
            if not last_sync:
                logger.info(f"No previous sync time for room {room_id}, fetching all available messages...")
            else:
                logger.info(f"Fetching messages for room {room_id} since {datetime.fromtimestamp(last_sync / 1000)}")

            try:
                # Fetch messages since last sync
                response = await self.matrix_client.room_messages(
                    room_id=room_id,
                    start=None if not last_sync else str(last_sync),
                    limit=100,
                    direction=MessageDirection.front
                )

                if isinstance(response, RoomMessagesResponse):
                    for event in response.chunk:
                        if isinstance(event, RoomMessageText):
                            # Create InfluxDB point
                            point = Point("matrix_message")\
                                .tag("sender", event.source.get('sender', event.sender))\
                                .tag("room_id", room_id)\
                                .tag("message_type", type(event).__name__)\
                                .field("content", event.body)\
                                .time(event.source.get('origin_server_ts', event.server_timestamp))

                            # Write to InfluxDB
                            self.write_api.write(
                                bucket=self.settings.influxdb.bucket,
                                record=point
                            )
                            logger.debug(f"Wrote message from {event.sender} in room {room_id} to InfluxDB")

                    # Update sync time for this room
                    if response.chunk:
                        self.room_sync_times[room_id] = response.chunk[-1].source.get(
                            'origin_server_ts',
                            response.chunk[-1].server_timestamp
                        )
                        self.save_sync_state()

                else:
                    logger.error(f"Failed to fetch messages from room {room_id}: {response}")

            except Exception as e:
                logger.error(f"Error fetching messages from room {room_id}: {e}")
                raise

    async def handle_message(self, room_id: str, event: RoomMessageText) -> None:
        """Process a single message event"""
        self.store_message_in_influx(
            room_id=room_id,
            sender=event.sender,
            message=event.body,
            timestamp=datetime.fromtimestamp(event.server_timestamp / 1000)
        )

    async def run(self) -> None:
        """Main run loop"""
        await self.connect_to_matrix()
        
        # Join the room if not already joined
        await self.matrix_client.join(self.settings.matrix.room_id)
        logger.info(f"Joined room {self.settings.matrix.room_id}")

        # Fetch historical messages first
        await self.fetch_historical_messages()

        # Add message callback for new messages
        self.matrix_client.add_event_callback(self.message_callback, RoomMessageText)

        # Start syncing
        logger.info("Starting sync loop for new messages...")
        await self.matrix_client.sync_forever(timeout=30000)

async def main() -> None:
    settings: Settings = Settings()
    
    # Set up logging before creating the bridge
    setup_logging(settings)
    logger.info("Starting Matrix to InfluxDB bridge")
    
    bridge: MatrixInfluxBridge = MatrixInfluxBridge(settings)
    try:
        await bridge.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await bridge.matrix_client.close()
        bridge.influx_client.close()

if __name__ == "__main__":
    asyncio.run(main())
