import os
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class MatrixConfig(BaseModel):
    homeserver: str
    user: str
    password: str
    room_ids: list[str] = []  # Empty list means all accessible rooms


class InfluxDBConfig(BaseModel):
    url: str
    token: str
    org: str
    bucket: str


class LogConfig(BaseModel):
    file_path: str = "logs/matrix_influx.log"
    max_size_mb: int = 10
    backup_count: int = 5
    level: str = "INFO"

class Settings(BaseSettings):
    matrix: MatrixConfig
    influxdb: InfluxDBConfig
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

        influxdb_config = InfluxDBConfig(
            url=os.environ.get('INFLUXDB_URL', ''),
            token=os.environ.get('INFLUXDB_TOKEN', ''),
            org=os.environ.get('INFLUXDB_ORG', ''),
            bucket=os.environ.get('INFLUXDB_BUCKET', '')
        )

        # Initialize with parsed configs
        super().__init__(
            matrix=matrix_config,
            influxdb=influxdb_config,
            **kwargs
        )
