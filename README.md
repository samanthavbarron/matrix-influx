# Matrix to InfluxDB Bridge

[![Tests](https://github.com/yourusername/matrix-to-influxdb/actions/workflows/tests.yml/badge.svg)](https://github.com/yourusername/matrix-to-influxdb/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/yourusername/matrix-to-influxdb/branch/main/graph/badge.svg)](https://codecov.io/gh/yourusername/matrix-to-influxdb)

This application scrapes messages from a Matrix Chat server and stores them in InfluxDB for analysis and monitoring.

## Prerequisites

- Python 3.7+
- A Matrix account and access to a Matrix homeserver
- InfluxDB 2.x instance running
- Access to a Matrix room you want to monitor

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Copy the `.env.example` file to `.env`:
   ```bash
   cp .env.example .env
   ```

3. Edit the `.env` file with your credentials:
   - Matrix configuration:
     - `MATRIX_HOMESERVER`: Your Matrix homeserver URL
     - `MATRIX_USER`: Your Matrix user ID
     - `MATRIX_PASSWORD`: Your Matrix password
     - `MATRIX_ROOM_ID`: The room ID to monitor
   - InfluxDB configuration:
     - `INFLUXDB_URL`: Your InfluxDB instance URL
     - `INFLUXDB_TOKEN`: Your InfluxDB API token
     - `INFLUXDB_ORG`: Your InfluxDB organization
     - `INFLUXDB_BUCKET`: The bucket to store messages in

## Running the Application

```bash
python matrix_to_influx.py
```

The application will:
1. Connect to the Matrix server
2. Join the specified room
3. Listen for new messages
4. Store each message in InfluxDB with metadata (sender, room, timestamp)

Press Ctrl+C to stop the application.
