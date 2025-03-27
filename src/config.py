import os
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class MatrixConfig(BaseModel):
    homeserver: str
    user: str
    password: str
    room_ids: list[str] = []  # Empty list means all accessible rooms


class PostgresConfig(BaseModel):
    """PostgreSQL configuration."""
    host: str
    port: int = 5432
    database: str
    user: str
    password: str
    store_content: bool = False  # Controls whether message content is stored

    @property
    def url(self) -> str:
        """Get the PostgreSQL connection URL."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class LogConfig(BaseModel):
    file_path: str = "logs/matrix_influx.log"
    max_size_mb: int = 10
    backup_count: int = 5
    level: str = "INFO"

class Settings(BaseSettings):
    matrix: MatrixConfig
    postgres: PostgresConfig
    sync_state_file: str = "matrix_sync_state.json"
    logging: LogConfig = LogConfig()

    class Config:
        env_nested_delimiter = '__'
        env_file = '.env'

    def __init__(self, **kwargs):
        # Parse room_ids from environment
        matrix_room_ids = []
        if 'MATRIX_ROOM_IDS' in os.environ:
            room_ids = os.environ['MATRIX_ROOM_IDS'].strip()
            if room_ids:
                matrix_room_ids = [r.strip() for r in room_ids.split(',')]

        # Create configs from environment
        matrix_config = MatrixConfig(
            homeserver=os.environ.get('MATRIX_HOMESERVER', ''),
            user=os.environ.get('MATRIX_USER', ''),
            password=os.environ.get('MATRIX_PASSWORD', ''),
            room_ids=matrix_room_ids
        )

        postgres_config = PostgresConfig(
            host=os.environ.get('POSTGRES_HOST', 'localhost'),
            port=int(os.environ.get('POSTGRES_PORT', '5432')),
            database=os.environ.get('POSTGRES_DB', ''),
            user=os.environ.get('POSTGRES_USER', ''),
            password=os.environ.get('POSTGRES_PASSWORD', ''),
            store_content=os.environ.get('POSTGRES_STORE_CONTENT', 'false').lower() == 'true'
        )

        # Initialize with parsed configs
        super().__init__(
            matrix=matrix_config,
            postgres=postgres_config,
            **kwargs
        )
