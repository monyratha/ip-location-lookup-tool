# IP Location Lookup Tool

This Flask web application lets you look up location information for individual IP addresses or bulk process CSV files containing an IP column named `client_ip`. Results are cached in a local SQLite database and summarized on a statistics page. You can also configure connections to MySQL databases and fetch IPs directly from any table.

## Setup

1. Install Python 3.8 or newer.
2. Install dependencies (MySQL features require `pymysql`):
   ```bash
   pip install -r requirements.txt
   ```
3. Copy the sample environment file and adjust values if needed:
   ```bash
   cp .env.example .env
   ```
4. Run the application:
   ```bash
   python app.py
   ```
5. Open `http://localhost:8080` (or the port set in `.env`) in your browser.

Optional: visit `/connections` in the UI to add MySQL connection details. Once
configured you can fetch IP data from any table on the main page. When fetching
from MySQL you can also specify a start and end time to run a query that counts
IP occurrences between those timestamps.

Use the `/settings` page to change the default table/column and tweak the
thresholds used for dynamic IP classification without editing `.env`.

Processed files are saved under `results/` and cached IP data is stored in the database defined by `DB_FILE`.

## Cached Data

The IP information retrieved from [ip-api.com](https://ip-api.com/) is stored in
the `ip_cache` table. In addition to country, region and city, the cache now
includes fields such as continent, latitude/longitude, ISP and more. This allows
subsequent lookups to return the full API response without making another
network request.
