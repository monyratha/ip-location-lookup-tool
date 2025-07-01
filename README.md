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
4. Run the application:
   ```bash
   python app.py
   ```
5. Open `http://localhost:8080` (or the port set in `.env`) in your browser.

Processed files are saved under `results/` and cached IP data is stored in the database defined by `DB_FILE`.
