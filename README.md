# IP Location Lookup Tool

This Flask web application lets you look up location information for individual IP addresses or bulk process CSV files containing an IP column named `client_ip`. Results are cached in a local SQLite database and summarized on a statistics page.

## Setup

1. Install Python 3.8 or newer.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy the sample environment file and adjust values if needed:
   ```bash
   cp .env.example .env
   ```
4. Start a Redis server (default connection uses `redis://localhost:6379/0`).
5. In one terminal, run the RQ worker:
   ```bash
   rq worker csv
   ```
6. In another terminal, run the application:
   ```bash
   python app.py
   ```
7. Open `http://localhost:8080` (or the port set in `.env`) in your browser.

Processed files are saved under `results/` and cached IP data is stored in the database defined by `DB_FILE`.

## Cached Data

The IP information retrieved from [ip-api.com](https://ip-api.com/) is stored in
the `ip_cache` table. In addition to country, region and city, the cache now
includes fields such as continent, latitude/longitude, ISP and more. This allows
subsequent lookups to return the full API response without making another
network request.
