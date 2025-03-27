import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, Optional

from nio import (
    AsyncClient,
    Event,
    LoginResponse,
    MatrixRoom,
    MessageDirection,
    RoomMessagesResponse,
    RoomMessageText,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from .config import Settings
from .logger import get_logger, setup_logging
from .schema import Base, Message

# Create logger for this module
logger = get_logger(__name__)


class MatrixInfluxBridge:
    def __init__(self, settings: Settings) -> None:
        self.settings: Settings = settings
        self.matrix_client: AsyncClient = AsyncClient(
            settings.matrix.homeserver, settings.matrix.user
        )
        self.engine = create_engine(settings.database.url)
        Base.metadata.create_all(self.engine)
        self.room_sync_times: Dict[str, Optional[int]] = {}
        self.last_sync_time: Optional[int] = None

        if not settings.matrix.room_ids:
            self.monitored_rooms = set(self.matrix_client.rooms.keys())
        else:
            self.monitored_rooms = set(settings.matrix.room_ids)
        self.load_sync_state()

    def load_sync_state(self) -> None:
        """Load the last sync timestamp for each room from file"""
        try:
            with open(self.settings.sync_state_file, "r") as f:
                state = json.load(f)
                self.room_sync_times = {room: ts for room, ts in state.items()}
                for room_id, timestamp in self.room_sync_times.items():
                    logger.info(f"Room {room_id} last sync time: {timestamp}")
        except FileNotFoundError:
            logger.info("No previous sync state found")
            self.room_sync_times = {}
        except json.JSONDecodeError:
            logger.warning("Corrupted sync state file found, starting fresh")
            self.room_sync_times = {}

    def save_sync_state(self) -> None:
        """Save the current sync timestamp for each room to file"""
        with open(self.settings.sync_state_file, "w") as f:
            json.dump(self.room_sync_times, f)

    async def connect_to_matrix(self) -> None:
        """Connect to Matrix server and join the specified room"""
        logger.info(f"Logging in to Matrix as {self.settings.matrix.user}...")
        response: LoginResponse = await self.matrix_client.login(
            password=self.settings.matrix.password
        )
        if not response.transport_response.ok:
            logger.error(
                f"Failed to log in with status code: {response.transport_response.status}"
            )
            raise Exception(f"Failed to log in: {response.transport_response.status}")
        logger.info("Successfully logged in")

    def store_message_in_db(
        self,
        room_id: str,
        sender: str,
        message: str,
        timestamp: datetime,
        message_type: str,
    ) -> None:
        """Store a Matrix message in PostgreSQL"""
        with Session(self.engine) as session:
            msg = Message(
                room_id=room_id,
                sender=sender,
                message_type=message_type,
                content=message if self.settings.postgres.store_content else None,
                content_length=len(message),
                timestamp=timestamp,
            )
            session.add(msg)
            session.commit()

    async def message_callback(self, room: MatrixRoom, event: Event) -> None:
        """Callback for new messages"""
        if isinstance(event, RoomMessageText):
            logger.debug(
                f"New message in {room.room_id} from {event.sender}: {event.body}"
            )
            await self.handle_message(room.room_id, event)

            # Update sync state with the latest message timestamp
            self.last_sync_time = max(event.server_timestamp, self.last_sync_time or 0)
            self.save_sync_state()

    async def fetch_historical_messages(self) -> None:
        """Fetch messages from all monitored rooms since their last sync time"""
        for room_id in self.monitored_rooms:
            last_sync = self.room_sync_times.get(room_id)
            if not last_sync:
                logger.info(
                    f"No previous sync time for room {room_id}, fetching all available messages..."
                )
            else:
                logger.info(f"Fetching messages for room {room_id} since {last_sync}")

            try:
                # Fetch messages since last sync
                response = await self.matrix_client.room_messages(
                    room_id=room_id,
                    start=None if not last_sync else str(last_sync),
                    limit=100,
                    direction=MessageDirection.front,
                )

                if isinstance(response, RoomMessagesResponse):
                    for event in response.chunk:
                        if isinstance(event, RoomMessageText):
                            # Store message in PostgreSQL
                            self.store_message_in_db(
                                room_id=room_id,
                                sender=event.source.get("sender", event.sender),
                                message=event.body,
                                timestamp=datetime.fromtimestamp(
                                    event.source.get(
                                        "origin_server_ts", event.server_timestamp
                                    )
                                    / 1000,
                                    tz=timezone.utc,
                                ),
                                message_type=type(event).__name__,
                            )
                            logger.debug(
                                f"Wrote message from {event.sender} in room {room_id} to PostgreSQL"
                            )

                    # Update sync time for this room
                    if response.chunk:
                        self.room_sync_times[room_id] = response.end
                        self.save_sync_state()

                else:
                    logger.error(
                        f"Failed to fetch messages from room {room_id}: {response}"
                    )

            except Exception as e:
                logger.error(f"Error fetching messages from room {room_id}: {e}")
                raise

    async def handle_message(self, room_id: str, event: RoomMessageText) -> None:
        """Process a single message event"""
        # Store message in PostgreSQL
        self.store_message_in_db(
            room_id=room_id,
            sender=event.source.get("sender", event.sender),
            message=event.body,
            timestamp=datetime.fromtimestamp(
                event.source.get("origin_server_ts", event.server_timestamp) / 1000,
                tz=timezone.utc,
            ),
            message_type=type(event).__name__,
        )

    async def run(self) -> None:
        """Main run loop"""
        await self.connect_to_matrix()

        # Join the room if not already joined
        for room_id in self.monitored_rooms:
            await self.matrix_client.join(room_id)
            logger.info(f"Monitoring room {room_id}")

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
    logger.info("Starting Matrix to PostgreSQL bridge")

    bridge: MatrixInfluxBridge = MatrixInfluxBridge(settings)
    try:
        await bridge.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await bridge.matrix_client.close()


if __name__ == "__main__":
    asyncio.run(main())
