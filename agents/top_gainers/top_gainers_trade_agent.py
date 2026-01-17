"""
Top Gainers Trade Agent

Monitors top gainers trend data and tracks buy/sell signals.
- If trend is "Up": Records buy signal (or prints "Invest" if new)
- If trend is "Down": Records sell signal (if there was a previous buy)
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.config import Config
from core.database import connect
from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)

TREND_TABLE_NAME = "yahoo_top_gainers_trend"
GAINERS_TABLE_NAME = "yahoo_top_gainers"
TRADES_TABLE_NAME = "yahoo_top_gainers_trades"


def init_trades_table(conn):
    """Initialize the trades table if it doesn't exist."""
    sql = f"""
    CREATE TABLE IF NOT EXISTS "{TRADES_TABLE_NAME}" (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        name TEXT,
        buy_price REAL,
        buy_time TEXT,
        sale_price REAL,
        sale_time TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(symbol, buy_time)
    );
    CREATE INDEX IF NOT EXISTS idx_trades_symbol_buy_time 
    ON "{TRADES_TABLE_NAME}"(symbol, buy_time DESC);
    """
    conn.executescript(sql)
    conn.commit()


def get_stock_name(db_path: str, symbol: str) -> Optional[str]:
    """Get stock name from yahoo_top_gainers table."""
    conn = connect(db_path)
    try:
        cur = conn.execute(
            f'SELECT "Name" FROM "{GAINERS_TABLE_NAME}" WHERE "Symbol" = ? ORDER BY "Scraped At (UTC)" DESC LIMIT 1',
            (symbol,)
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()


def get_latest_trends(db_path: str) -> List[Dict]:
    """Get latest trend data for all symbols."""
    conn = connect(db_path)
    try:
        # Get the latest scrape timestamp
        cur = conn.execute(f'SELECT MAX("Scraped At (UTC)") FROM "{TREND_TABLE_NAME}"')
        latest_ts = cur.fetchone()[0]
        
        if not latest_ts:
            return []
        
        # Get all trends from latest scrape
        cur = conn.execute(
            f'''
            SELECT "Symbol", "Trend", "Now", "Scraped At (UTC)"
            FROM "{TREND_TABLE_NAME}"
            WHERE "Scraped At (UTC)" = ?
            ORDER BY "Symbol" ASC
            ''',
            (latest_ts,)
        )
        
        trends = []
        for row in cur.fetchall():
            trends.append({
                "Symbol": row[0],
                "Trend": row[1],
                "Price": row[2],
                "Scraped At": row[3]
            })
        
        return trends
    finally:
        conn.close()


def get_open_position(db_path: str, symbol: str) -> Optional[Dict]:
    """Get the most recent open position (buy without sale) for a symbol."""
    conn = connect(db_path)
    try:
        cur = conn.execute(
            f'''
            SELECT id, symbol, name, buy_price, buy_time
            FROM "{TRADES_TABLE_NAME}"
            WHERE symbol = ? AND sale_price IS NULL AND sale_time IS NULL
            ORDER BY buy_time DESC
            LIMIT 1
            ''',
            (symbol,)
        )
        row = cur.fetchone()
        if row:
            return {
                "id": row[0],
                "symbol": row[1],
                "name": row[2],
                "buy_price": row[3],
                "buy_time": row[4]
            }
        return None
    finally:
        conn.close()


def has_latest_buy(db_path: str, symbol: str) -> bool:
    """Check if the latest trade record for a symbol is already a buy (open position)."""
    open_position = get_open_position(db_path, symbol)
    return open_position is not None


def record_buy(db_path: str, symbol: str, name: Optional[str], price: float, buy_time: str):
    """Record a buy signal."""
    conn = connect(db_path)
    try:
        init_trades_table(conn)
        
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        
        conn.execute(
            f'''
            INSERT INTO "{TRADES_TABLE_NAME}"
            (symbol, name, buy_price, buy_time, created_at)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (symbol, name, price, buy_time, created_at)
        )
        conn.commit()
        logger.info(f"Recorded BUY: {symbol} ({name}) at ${price:.2f} at {buy_time}")
    except Exception as e:
        logger.error(f"Error recording buy for {symbol}: {e}", exc_info=True)
    finally:
        conn.close()


def record_sale(db_path: str, trade_id: int, symbol: str, price: float, sale_time: str):
    """Record a sell signal for an existing buy."""
    conn = connect(db_path)
    try:
        # Get buy price before updating
        cur = conn.execute(f'SELECT buy_price FROM "{TRADES_TABLE_NAME}" WHERE id = ?', (trade_id,))
        row = cur.fetchone()
        buy_price = row[0] if row else None
        
        # Update with sale information
        conn.execute(
            f'''
            UPDATE "{TRADES_TABLE_NAME}"
            SET sale_price = ?, sale_time = ?
            WHERE id = ?
            ''',
            (price, sale_time, trade_id)
        )
        conn.commit()
        
        if buy_price:
            profit = price - buy_price
            profit_pct = ((price - buy_price) / buy_price) * 100 if buy_price > 0 else 0
            logger.info(
                f"Recorded SALE: {symbol} at ${price:.2f} at {sale_time} "
                f"(Bought: ${buy_price:.2f}, Profit: ${profit:.2f} ({profit_pct:+.2f}%))"
            )
        else:
            logger.info(f"Recorded SALE: {symbol} at ${price:.2f} at {sale_time}")
    except Exception as e:
        logger.error(f"Error recording sale for {symbol}: {e}", exc_info=True)
    finally:
        conn.close()


def process_trade_signals(cfg: Config):
    """Process trend data and generate buy/sell signals."""
    logger.info("="*60)
    logger.info("Top Gainers Trade Agent - Processing Trade Signals")
    logger.info("="*60)
    
    # Get latest trends
    logger.info("Fetching latest trend data...")
    trends = get_latest_trends(cfg.sqlite_path)
    
    if not trends:
        logger.warning("No trend data found")
        return
    
    logger.info(f"Found {len(trends)} symbols with trend data")
    
    # Initialize trades table
    conn = connect(cfg.sqlite_path)
    try:
        init_trades_table(conn)
    finally:
        conn.close()
    
    invest_list = []
    buy_count = 0
    sell_count = 0
    
    for trend_data in trends:
        symbol = trend_data["Symbol"]
        trend = trend_data["Trend"]
        price = trend_data.get("Price")
        scraped_at = trend_data.get("Scraped At")
        
        if not price:
            logger.warning(f"{symbol}: No price data, skipping")
            continue
        
        # Get stock name
        name = get_stock_name(cfg.sqlite_path, symbol)
        
        if trend == "Up":
            # If Up signal: if last record is NOT an open position, open a new position
            # Otherwise, keep it as open (do nothing)
            open_position = get_open_position(cfg.sqlite_path, symbol)
            
            if not open_position:
                # No open position exists, open a new position
                record_buy(cfg.sqlite_path, symbol, name, float(price), scraped_at)
                buy_count += 1
                invest_list.append({"symbol": symbol, "name": name, "price": price})
                logger.info(f"BUY signal: {symbol} - {name or 'N/A'} (Price: ${price:.2f}) - Opening new position")
                print(f"INVEST: {symbol} - {name or 'N/A'} (Price: ${price:.2f})")
            else:
                # Already have an open position, keep it as open (do nothing)
                logger.debug(f"{symbol}: Trend is Up, position already open at ${open_position['buy_price']:.2f} - keeping position open")
        
        elif trend == "Down":
            # If Down signal: close the position if it's open, otherwise do nothing
            open_position = get_open_position(cfg.sqlite_path, symbol)
            
            if open_position:
                # Position is open, close it (record sale with timestamp)
                record_sale(cfg.sqlite_path, open_position["id"], symbol, float(price), scraped_at)
                sell_count += 1
                logger.info(f"SELL signal: {symbol} at ${price:.2f} - Closing position (bought at ${open_position['buy_price']:.2f})")
            else:
                # No open position, nothing to close
                logger.debug(f"{symbol}: Trend is Down, but no open position to close - doing nothing")
    
    # Summary
    logger.info("="*60)
    logger.info(f"Trade Signals Summary:")
    logger.info(f"  Total symbols analyzed: {len(trends)}")
    logger.info(f"  New BUY signals: {buy_count}")
    logger.info(f"  SALE signals: {sell_count}")
    logger.info(f"  Current INVEST list: {len(invest_list)} stocks")
    logger.info("="*60)
    
    if invest_list:
        logger.info("INVEST List:")
        for item in invest_list:
            logger.info(f"  - {item['symbol']}: {item['name'] or 'N/A'} @ ${item['price']:.2f}")
            print(f"INVEST: {item['symbol']} - {item['name'] or 'N/A'} (Price: ${item['price']:.2f})")


def main():
    """Main entry point for top gainers trade agent."""
    setup_logging("INFO", "top_gainers_trade.log")
    
    try:
        cfg = Config.from_env()
        process_trade_signals(cfg)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
