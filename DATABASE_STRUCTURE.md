# Database Structure

## Overview

The system uses a **single SQLite database** stored in the `database/` folder:

- **Main Database** (`database/stock_analysis.db`) - Contains all tables for historical OHLC data, signals, alerts, and news
- **CrewAI State** (`database/state.sqlite`) - CrewAI's internal state file (auto-created)

This single database approach provides:
- Simpler setup and maintenance
- Single point of backup
- All data in one place for easier querying
- Clear separation via table structure
- Organized storage in dedicated `database/` folder

## Database Location

**Path:** `database/stock_analysis.db` (configurable via `SQLITE_PATH`)

All database files are stored in the `database/` folder:
- `database/stock_alerts.db` - Main application database
- `database/state.sqlite` - CrewAI state (auto-created by CrewAI)

## Database Schema

All tables are stored in a single database:

### Historical Data Tables

```sql
-- Daily OHLC data (backfill)
CREATE TABLE stock_history (
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume REAL NOT NULL,
  source TEXT DEFAULT 'twelve_data',
  ingested_at TEXT NOT NULL,
  PRIMARY KEY(symbol, date)
);

CREATE INDEX idx_stock_history_symbol_date 
  ON stock_history(symbol, date DESC);

-- Ingestion log (backfill tracking)
CREATE TABLE ingestion_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  date_range_start TEXT,
  date_range_end TEXT,
  status TEXT NOT NULL,
  records_ingested INTEGER DEFAULT 0,
  error_message TEXT,
  created_at TEXT NOT NULL
);
```

### Monitoring Data Tables

```sql
-- Signals (triggered events)
CREATE TABLE signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  datetime TEXT NOT NULL,
  signal_type TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  severity TEXT NOT NULL,
  created_at TEXT NOT NULL,
  bar_id TEXT,
  UNIQUE(symbol, signal_type, bar_id)
);

CREATE INDEX idx_signals_symbol_datetime 
  ON signals(symbol, datetime DESC);

-- Alert log (throttling)
CREATE TABLE alert_log (
  symbol TEXT NOT NULL,
  last_alert_at TEXT,
  last_alert_price REAL,
  last_alert_direction TEXT,
  last_alert_severity TEXT,
  PRIMARY KEY(symbol)
);

-- News items
CREATE TABLE news_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  published_at TEXT,
  title TEXT NOT NULL,
  source TEXT,
  url TEXT NOT NULL,
  query TEXT,
  hash TEXT NOT NULL,
  UNIQUE(hash)
);

CREATE INDEX idx_news_items_hash 
  ON news_items(hash);

-- Signal-News links
CREATE TABLE signal_news_links (
  signal_id INTEGER NOT NULL,
  news_id INTEGER NOT NULL,
  relevance_label TEXT NOT NULL,
  PRIMARY KEY(signal_id, news_id),
  FOREIGN KEY(signal_id) REFERENCES signals(id),
  FOREIGN KEY(news_id) REFERENCES news_items(id)
);

-- Historical OHLC-News links (for backfilled data analysis)
CREATE TABLE ohlc_news_links (
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  news_id INTEGER NOT NULL,
  relevance_label TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(symbol, date, news_id),
  FOREIGN KEY(news_id) REFERENCES news_items(id)
);

CREATE INDEX idx_ohlc_news_links_symbol_date 
  ON ohlc_news_links(symbol, date DESC);

-- Top Gainers with News Summary
CREATE TABLE top_gainers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  start_price REAL NOT NULL,
  current_price REAL NOT NULL,
  change_pct REAL NOT NULL,
  news_summary TEXT,
  detected_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_top_gainers_symbol_detected 
  ON top_gainers(symbol, detected_at DESC);
```

## Table Usage

### Historical Data Tables
- **`stock_history`**: Stores daily OHLC price data
  - Used by: `agents/backfill_agent.py`, `agents/eod_agent.py`
  - Read by: `agents/monitor_agent.py` (for day open prices)

- **`ingestion_log`**: Tracks backfill operations
  - Used by: `agents/backfill_agent.py`

### Monitoring Data Tables
- **`signals`**: Detected trading signals
  - Used by: `agents/monitor_agent.py`
  - Read by: `agents/news_agent.py`, `main.py`

- **`alert_log`**: Alert throttling/cooldown tracking
  - Used by: `agents/monitor_agent.py`
  - Read by: `agents/monitor_agent.py` (for throttling logic)

- **`news_items`**: Fetched news articles
  - Used by: `agents/news_agent.py`
  - Read by: `agents/summarizer_agent.py`, `main.py`

- **`signal_news_links`**: Links between signals and news
  - Used by: `agents/news_agent.py`
  - Read by: `agents/summarizer_agent.py`, `main.py`

- **`ohlc_news_links`**: Links between historical OHLC records and news
  - Used by: `agents/historical_news_agent.py`
  - Read by: `agents/historical_news_agent.py` (for querying linked news)

- **`top_gainers`**: Top gainers scraped from Yahoo Finance
  - Used by: `agents/top_gainers_scrape_agent.py`
  - Stores: symbol, start price, current price, change %, news summary (optional)
  - Note: Old data is cleared and replaced with new data on each scrape

## Configuration

In your `.env` file:

```bash
# Single SQLite database for all data (stored in database/ folder)
SQLITE_PATH=database/stock_analysis.db
```

## File Structure

```
Stock-Ayalyst/
├── database/
│   ├── stock_analysis.db  # Main database with all tables
│   └── state.sqlite       # CrewAI state (auto-created)
├── data/
│   └── sector_map.json    # Sector mapping
├── ...
```

## Benefits of Single Database

1. **Simplicity**: 
   - One database file to manage
   - Single backup point
   - Easier to understand

2. **Querying**:
   - Can easily join data across tables
   - Single connection for all operations
   - Simpler data analysis

3. **Maintenance**:
   - One file to backup/restore
   - Single point of configuration
   - Easier migration if needed

## Backup Recommendations

```bash
# Backup the entire database folder
cp -r database/ backups/database_$(date +%Y%m%d_%H%M)/

# Or backup just the main database
cp database/stock_analysis.db backups/stock_analysis_$(date +%Y%m%d_%H%M).db
```

## Database Connection

All database operations use the `connect()` function from `core.database`, which:
- Creates the database file if it doesn't exist
- Initializes all tables with the complete schema
- Enables WAL (Write-Ahead Logging) mode for better concurrency

Example:
```python
from core.database import connect

conn = connect("database/stock_analysis.db")
# All tables are available in this connection
```

## CrewAI State File

CrewAI automatically creates `state.sqlite` in the current working directory. The system is configured to change to the `database/` folder when running CrewAI operations, ensuring `state.sqlite` is created in the correct location alongside the main database.
