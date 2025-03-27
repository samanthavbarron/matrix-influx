# Post-Mortem

This was a test of me learning how to use Windsurf and Cursor (mainly Windsurf). Almost all of the code in this repo is AI generated.

My initial idea for this project was that I would like all of my messages on my Matrix homeserver to be available to me in some sort of time series database. I have some previous familiarity with InfluxDB, so I started there. My goal in doing this with Windsurf/Cursor was to test out these tools and learn how to use them for myself.

In doing so, I learned a few things:
- As far as I can tell, these tools can function autonomously for a little bit, but are not currently designed to be entirely hands off (to be clear, I don't think they're advertised this way either).
- It's very easy to get the AI run wild to the point where I don't intuitively understand the intent of the code.
- InfluxDB was probably not a good initial choice for how to store the messages.
- I become less personally invested in the project as I started to understand the code less.
- I was unfortunately able to get neither tool to work with devcontainers. This was a huge limitation and I expect that devcontainers or something like it will be very important for making coding agents viable.

There are likely better ways of using these tools, and I expect a more seasoned Windsurfer/Cursorer would have suggestions for how to address these points.

As for the project, I am going to archive this because at this point it's fairly mangled. I plan on starting over and making a much simpler implementation. And I plan on doing it the old fasioned way.

# Matrix to InfluxDB Bridge

**NOTE FROM SAMANTHA:** This code was almost entirely generated with Windsurf.

[![Tests](https://github.com/samanthavbarron/matrix-to-influxdb/actions/workflows/tests.yml/badge.svg)](https://github.com/samanthavbarron/matrix-to-influxdb/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/samanthavbarron/matrix-to-influxdb/branch/main/graph/badge.svg)](https://codecov.io/gh/samanthavbarron/matrix-to-influxdb)

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
     - `INFLUXDB_STORE_CONTENT`: (Optional) Set to 'false' to disable storing message content, defaults to 'true'

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
