"""Agent for backfilling historical OHLC data."""
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import Config
from core.database import connect, store_daily_ohlc, log_ingestion
from core.tools import fetch_time_series
from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


def backfill_symbol(api_key: str, symbol: str, days: int, db_path: str) -> bool:
    """Backfill historical data for a symbol."""
    logger.info(f"Backfilling {days} days of data for {symbol}...")
    
    conn = connect(db_path)
    try:
        # Check if we already have data
        cur = conn.execute(
            "SELECT COUNT(*) FROM ohlc_daily WHERE symbol=?",
            (symbol,)
        )
        existing_count = cur.fetchone()[0]
        
        if existing_count >= days * 0.9:
            logger.info(f"{symbol}: Already has {existing_count} days, skipping")
            return True
        
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # Fetch data (1day interval)
        bars = fetch_time_series(api_key, symbol, "1day", min(days, 5000))
        
        if not bars:
            log_ingestion(conn, symbol, "failed", 0, 
                         start_date.strftime("%Y-%m-%d"),
                         end_date.strftime("%Y-%m-%d"),
                         "No data returned from API")
            return False
        
        # Store bars
        stored = 0
        for bar in bars:
            date_str = bar.get("datetime", "").split()[0]  # Extract date part
            if not date_str:
                continue
            
            stored += store_daily_ohlc(
                conn,
                symbol,
                date_str,
                float(bar.get("open", 0)),
                float(bar.get("high", 0)),
                float(bar.get("low", 0)),
                float(bar.get("close", 0)),
                float(bar.get("volume", 0))
            )
        
        log_ingestion(conn, symbol, "success", stored,
                     start_date.strftime("%Y-%m-%d"),
                     end_date.strftime("%Y-%m-%d"))
        
        logger.info(f"{symbol}: Stored {stored} daily OHLC records")
        return True
        
    except Exception as e:
        logger.error(f"Error backfilling {symbol}: {e}", exc_info=True)
        log_ingestion(conn, symbol, "error", 0, error_message=str(e))
        return False
    finally:
        conn.close()


def main():
    """Main entry point for backfill agent."""
    setup_logging("INFO", "backfill.log")
    
    try:
        cfg = Config.from_env()
        
        if not cfg.twelve_data_api_key:
            raise ValueError("TWELVE_DATA_API_KEY is required")
        
        logger.info(f"Starting backfill for {len(cfg.watchlist)} symbols...")
        
        for symbol in cfg.watchlist:
            try:
                backfill_symbol(
                    cfg.twelve_data_api_key,
                    symbol,
                    cfg.history_days,
                    cfg.sqlite_path
                )
                # Be polite to API
                import time
                time.sleep(1)
            except Exception as e:
                logger.error(f"Failed to backfill {symbol}: {e}")
        
        logger.info("Backfill completed")
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
