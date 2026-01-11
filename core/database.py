"""Database schema and operations."""
import sqlite3
from typing import Optional, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Single database schema with all tables
SCHEMA = """
-- Daily OHLC data (historical/backfill)
CREATE TABLE IF NOT EXISTS ohlc_daily (
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

CREATE INDEX IF NOT EXISTS idx_ohlc_daily_symbol_date 
  ON ohlc_daily(symbol, date DESC);

-- Ingestion log (backfill tracking)
CREATE TABLE IF NOT EXISTS ingestion_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  date_range_start TEXT,
  date_range_end TEXT,
  status TEXT NOT NULL,
  records_ingested INTEGER DEFAULT 0,
  error_message TEXT,
  created_at TEXT NOT NULL
);

-- Signals (triggered events)
CREATE TABLE IF NOT EXISTS signals (
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

CREATE INDEX IF NOT EXISTS idx_signals_symbol_datetime 
  ON signals(symbol, datetime DESC);

-- Alert log (throttling)
CREATE TABLE IF NOT EXISTS alert_log (
  symbol TEXT NOT NULL,
  last_alert_at TEXT,
  last_alert_price REAL,
  last_alert_direction TEXT,
  last_alert_severity TEXT,
  PRIMARY KEY(symbol)
);

-- News items
CREATE TABLE IF NOT EXISTS news_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  published_at TEXT,
  title TEXT NOT NULL,
  source TEXT,
  url TEXT NOT NULL,
  query TEXT,
  hash TEXT NOT NULL,
  UNIQUE(hash)
);

CREATE INDEX IF NOT EXISTS idx_news_items_hash 
  ON news_items(hash);

-- Signal-News links
CREATE TABLE IF NOT EXISTS signal_news_links (
  signal_id INTEGER NOT NULL,
  news_id INTEGER NOT NULL,
  relevance_label TEXT NOT NULL,
  PRIMARY KEY(signal_id, news_id),
  FOREIGN KEY(signal_id) REFERENCES signals(id),
  FOREIGN KEY(news_id) REFERENCES news_items(id)
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Connect to database and initialize all tables."""
    from pathlib import Path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA)
    return conn


def store_daily_ohlc(
    db_path: str,
    symbol: str,
    date: str,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    source: str = "twelve_data"
) -> int:
    """Store daily OHLC data."""
    conn = connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO ohlc_daily 
               (symbol, date, open, high, low, close, volume, source, ingested_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol, date, open_price, high, low, close, volume, source, datetime.utcnow().isoformat())
        )
        conn.commit()
        return 1
    except Exception as e:
        logger.error(f"Error storing OHLC for {symbol} on {date}: {e}")
        return 0
    finally:
        conn.close()


def get_daily_ohlc(
    db_path: str,
    symbol: str,
    date: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """Get daily OHLC for symbol and date."""
    conn = connect(db_path)
    try:
        if date:
            cur = conn.execute(
                "SELECT * FROM ohlc_daily WHERE symbol=? AND date=?",
                (symbol, date)
            )
        else:
            cur = conn.execute(
                "SELECT * FROM ohlc_daily WHERE symbol=? ORDER BY date DESC LIMIT 1",
                (symbol,)
            )
        row = cur.fetchone()
        if row:
            return {
                "symbol": row[0],
                "date": row[1],
                "open": row[2],
                "high": row[3],
                "low": row[4],
                "close": row[5],
                "volume": row[6],
            }
        return None
    finally:
        conn.close()


def log_ingestion(
    db_path: str,
    symbol: str,
    status: str,
    records_ingested: int = 0,
    date_range_start: Optional[str] = None,
    date_range_end: Optional[str] = None,
    error_message: Optional[str] = None
):
    """Log ingestion attempt."""
    conn = connect(db_path)
    try:
        conn.execute(
            """INSERT INTO ingestion_log 
               (symbol, date_range_start, date_range_end, status, records_ingested, error_message, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (symbol, date_range_start, date_range_end, status, records_ingested, error_message, datetime.utcnow().isoformat())
        )
        conn.commit()
    finally:
        conn.close()


def store_signal(
    db_path: str,
    symbol: str,
    datetime_str: str,
    signal_type: str,
    metrics: dict[str, Any],
    severity: str,
    bar_id: Optional[str] = None
) -> Optional[int]:
    """Store signal. Returns signal_id if inserted, None if duplicate."""
    import json
    conn = connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO signals (symbol, datetime, signal_type, metrics_json, severity, created_at, bar_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (symbol, datetime_str, signal_type, json.dumps(metrics), severity, datetime.utcnow().isoformat(), bar_id)
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        # Duplicate signal
        return None
    except Exception as e:
        logger.error(f"Error storing signal: {e}")
        return None
    finally:
        conn.close()


def get_last_alert(db_path: str, symbol: str) -> Optional[dict[str, Any]]:
    """Get last alert info for symbol."""
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "SELECT * FROM alert_log WHERE symbol=?",
            (symbol,)
        )
        row = cur.fetchone()
        if row:
            return {
                "symbol": row[0],
                "last_alert_at": row[1],
                "last_alert_price": row[2],
                "last_alert_direction": row[3],
                "last_alert_severity": row[4],
            }
        return None
    finally:
        conn.close()


def update_alert_log(
    db_path: str,
    symbol: str,
    price: float,
    direction: str,
    severity: str
):
    """Update alert log."""
    conn = connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO alert_log 
               (symbol, last_alert_at, last_alert_price, last_alert_direction, last_alert_severity)
               VALUES (?, ?, ?, ?, ?)""",
            (symbol, datetime.utcnow().isoformat(), price, direction, severity)
        )
        conn.commit()
    finally:
        conn.close()


def store_news_item(
    db_path: str,
    title: str,
    url: str,
    published_at: Optional[str],
    source: Optional[str],
    query: Optional[str],
    url_hash: str
) -> int:
    """Store news item. Returns news_id."""
    conn = connect(db_path)
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO news_items 
               (published_at, title, source, url, query, hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (published_at, title, source, url, query, url_hash)
        )
        conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        # Already exists, get ID
        cur = conn.execute("SELECT id FROM news_items WHERE hash=?", (url_hash,))
        row = cur.fetchone()
        return row[0] if row else 0
    except Exception as e:
        logger.error(f"Error storing news item: {e}")
        return 0
    finally:
        conn.close()


def link_signal_news(
    db_path: str,
    signal_id: int,
    news_id: int,
    relevance_label: str
):
    """Link signal to news item."""
    conn = connect(db_path)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO signal_news_links (signal_id, news_id, relevance_label)
               VALUES (?, ?, ?)""",
            (signal_id, news_id, relevance_label)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Error linking signal-news: {e}")
    finally:
        conn.close()


def get_signals_with_news(
    db_path: str,
    since: Optional[str] = None
) -> list[dict[str, Any]]:
    """Get signals with linked news."""
    import json
    conn = connect(db_path)
    try:
        if since:
            cur = conn.execute(
                """SELECT s.id, s.symbol, s.datetime, s.signal_type, s.metrics_json, s.severity,
                          GROUP_CONCAT(n.title || '|' || n.url || '|' || snl.relevance_label, '|||') as news
                   FROM signals s
                   LEFT JOIN signal_news_links snl ON s.id = snl.signal_id
                   LEFT JOIN news_items n ON snl.news_id = n.id
                   WHERE s.datetime >= ?
                   GROUP BY s.id
                   ORDER BY s.datetime DESC""",
                (since,)
            )
        else:
            cur = conn.execute(
                """SELECT s.id, s.symbol, s.datetime, s.signal_type, s.metrics_json, s.severity,
                          GROUP_CONCAT(n.title || '|' || n.url || '|' || snl.relevance_label, '|||') as news
                   FROM signals s
                   LEFT JOIN signal_news_links snl ON s.id = snl.signal_id
                   LEFT JOIN news_items n ON snl.news_id = n.id
                   GROUP BY s.id
                   ORDER BY s.datetime DESC
                   LIMIT 50""",
            )
        
        results = []
        for row in cur.fetchall():
            news_data = []
            if row[6]:  # news column
                for news_str in row[6].split("|||"):
                    parts = news_str.split("|")
                    if len(parts) >= 3:
                        news_data.append({
                            "title": parts[0],
                            "url": parts[1],
                            "relevance": parts[2]
                        })
            
            results.append({
                "id": row[0],
                "symbol": row[1],
                "datetime": row[2],
                "signal_type": row[3],
                "metrics": json.loads(row[4]),
                "severity": row[5],
                "news": news_data
            })
        
        return results
    finally:
        conn.close()
