"""End-of-day agent for storing final OHLC and integrity checks."""
import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import Config
from core.database import store_daily_ohlc, get_daily_ohlc
from core.tools import fetch_time_series
from utils.market_hours import get_today_date
from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


def run_eod_processing(cfg: Config):
    """Run end-of-day processing for all symbols."""
    logger.info("Starting end-of-day processing...")
    
    today = get_today_date()
    
    for symbol in cfg.watchlist:
        try:
            # Fetch today's final daily data
            bars = fetch_time_series(cfg.twelve_data_api_key, symbol, "1day", 1)
            
            if bars:
                latest = bars[-1]
                date_str = latest.get("datetime", "").split()[0]
                
                if date_str == today:
                    # Store/update today's OHLC in historical database
                    store_daily_ohlc(
                        cfg.sqlite_path,
                        symbol,
                        date_str,
                        float(latest.get("open", 0)),
                        float(latest.get("high", 0)),
                        float(latest.get("low", 0)),
                        float(latest.get("close", 0)),
                        float(latest.get("volume", 0))
                    )
                    logger.info(f"{symbol}: Stored EOD data for {date_str}")
                else:
                    logger.warning(f"{symbol}: Latest data is not for today ({date_str} vs {today})")
            else:
                logger.warning(f"{symbol}: No data returned for EOD")
            
            # Integrity check: verify we have data
            daily = get_daily_ohlc(cfg.sqlite_path, symbol, today)
            if not daily:
                logger.warning(f"{symbol}: Missing EOD data for {today}")
            else:
                logger.info(f"{symbol}: EOD integrity check passed")
            
            import time
            time.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Error processing EOD for {symbol}: {e}", exc_info=True)
    
    logger.info("End-of-day processing completed")


def main():
    """Main entry point for EOD agent."""
    setup_logging("INFO", "eod.log")
    
    try:
        cfg = Config.from_env()
        
        if not cfg.twelve_data_api_key:
            raise ValueError("TWELVE_DATA_API_KEY is required")
        
        run_eod_processing(cfg)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
