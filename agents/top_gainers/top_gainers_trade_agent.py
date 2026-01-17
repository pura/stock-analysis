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
    hold_count = 0
    no_action_count = 0
    
    # Print and log header
    header = "\n" + "="*80 + "\n" + "TRADE SIGNALS FOR ALL SYMBOLS\n" + "="*80
    table_header = f"{'#':<4} {'Symbol':<8} {'Name':<30} {'Trend':<6} {'Price':<10} {'Signal':<20} {'Action':<15}\n" + "-"*80
    print(header)
    print(table_header)
    logger.info(header)
    logger.info(table_header)
    
    for i, trend_data in enumerate(trends, start=1):
        symbol = trend_data["Symbol"]
        trend = trend_data["Trend"]
        price = trend_data.get("Price")
        scraped_at = trend_data.get("Scraped At")
        
        if not price:
            logger.warning(f"{symbol}: No price data, skipping")
            no_data_line = f"{i:<4} {symbol:<8} {'N/A':<30} {'N/A':<6} {'N/A':<10} {'NO DATA':<20} {'SKIP':<15}"
            print(no_data_line)
            logger.info(no_data_line)
            continue
        
        # Get stock name
        name = get_stock_name(cfg.sqlite_path, symbol)
        display_name = (name or 'N/A')[:28]  # Truncate if too long
        
        # Get open position status
        open_position = get_open_position(cfg.sqlite_path, symbol)
        
        signal = ""
        action = ""
        action_taken = False
        
        if trend == "Up":
            if not open_position:
                # No open position exists, open a new position
                record_buy(cfg.sqlite_path, symbol, name, float(price), scraped_at)
                buy_count += 1
                invest_list.append({"symbol": symbol, "name": name, "price": price})
                signal = "🟢 BUY"
                action = "NEW POSITION"
                action_taken = True
                logger.info(f"BUY signal: {symbol} - {name or 'N/A'} (Price: ${price:.2f}) - Opening new position")
            else:
                # Already have an open position, keep it as open
                buy_price = open_position['buy_price']
                profit = price - buy_price
                profit_pct = ((price - buy_price) / buy_price * 100) if buy_price > 0 else 0
                signal = "🟢 BUY (HOLD)"
                action = f"HOLD @ ${buy_price:.2f}"
                hold_count += 1
                logger.debug(f"{symbol}: Trend is Up, position already open at ${buy_price:.2f} - keeping position open")
        
        elif trend == "Down":
            if open_position:
                # Position is open, close it
                buy_price = open_position['buy_price']
                record_sale(cfg.sqlite_path, open_position["id"], symbol, float(price), scraped_at)
                sell_count += 1
                profit = price - buy_price
                profit_pct = ((price - buy_price) / buy_price * 100) if buy_price > 0 else 0
                signal = "🔴 SELL"
                action = f"CLOSE @ ${price:.2f}"
                action_taken = True
                logger.info(f"SELL signal: {symbol} at ${price:.2f} - Closing position (bought at ${buy_price:.2f}, profit: ${profit:.2f} ({profit_pct:+.2f}%))")
            else:
                # No open position, nothing to close
                signal = "🔴 SELL"
                action = "NO POSITION"
                no_action_count += 1
                logger.debug(f"{symbol}: Trend is Down, but no open position to close - doing nothing")
        
        # Print and log signal for this symbol
        signal_line = f"{i:<4} {symbol:<8} {display_name:<30} {trend:<6} ${price:<9.2f} {signal:<20} {action:<15}"
        print(signal_line)
        logger.info(signal_line)
    
    # Print and log summary
    summary_separator = "="*80
    summary_header = "\n" + summary_separator + "\n" + "TRADE SIGNALS SUMMARY\n" + summary_separator
    summary_lines = [
        f"Total symbols analyzed: {len(trends)}",
        f"🟢 New BUY signals (new positions opened): {buy_count}",
        f"🟢 HOLD signals (positions maintained): {hold_count}",
        f"🔴 SELL signals (positions closed): {sell_count}",
        f"🔴 NO ACTION (no position to close): {no_action_count}",
        f"Current open positions: {buy_count + hold_count}",
        summary_separator
    ]
    
    print(summary_separator)
    print(summary_header)
    for line in summary_lines:
        print(line)
        logger.info(line)
    
    if invest_list:
        invest_header = "\n" + summary_separator + "\n" + "NEW POSITIONS OPENED (INVEST NOW)\n" + summary_separator
        print(invest_header)
        logger.info(invest_header)
        for item in invest_list:
            invest_line = f"🟢 BUY: {item['symbol']} - {item['name'] or 'N/A'} @ ${item['price']:.2f}"
            print(invest_line)
            logger.info(invest_line)
        print(summary_separator)
        logger.info(summary_separator)


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
