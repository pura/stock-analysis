"""
Top Gainers Cleanup Agent

Deletes records from yahoo_top_gainers table that are NOT from today.
Keeps only records from today.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.config import Config
from core.database import connect
from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)

TABLE_NAME = "yahoo_top_gainers"


def cleanup_old_records(db_path: str):
    """
    Clean up old records from yahoo_top_gainers table.
    Deletes all records EXCEPT those from today.
    Keeps only today's records.
    """
    conn = connect(db_path)
    try:
        # Get today's date
        now = datetime.now(timezone.utc)
        today_str = now.strftime("%Y-%m-%d")
        
        logger.info(f"Cleanup: Keeping only records from today ({today_str})")
        
        # Delete all records EXCEPT those from today
        # Extract date from "Scraped At (UTC)" timestamp (format: "2025-01-11T15:30:00")
        cur = conn.execute(
            f'''
            DELETE FROM "{TABLE_NAME}"
            WHERE date(substr("Scraped At (UTC)", 1, 10)) != date(?)
            ''',
            (today_str,)
        )
        deleted_count = cur.rowcount
        
        conn.commit()
        
        logger.info(f"Deleted {deleted_count} records (kept only today: {today_str})")
        
        # Get remaining count
        cur = conn.execute(f'SELECT COUNT(*) FROM "{TABLE_NAME}"')
        remaining_count = cur.fetchone()[0]
        logger.info(f"Remaining records in table: {remaining_count}")
        
        return deleted_count
        
    except Exception as e:
        logger.error(f"Error during cleanup: {e}", exc_info=True)
        return 0
    finally:
        conn.close()


def main():
    """Main entry point for cleanup agent."""
    setup_logging("INFO", "top_gainers_cleanup.log")
    
    try:
        cfg = Config.from_env()
        
        logger.info("="*60)
        logger.info("Top Gainers Cleanup Agent - Starting")
        logger.info("="*60)
        
        # Cleanup: keep only today's records
        deleted = cleanup_old_records(cfg.sqlite_path)
        
        logger.info("="*60)
        logger.info(f"Cleanup completed: {deleted} records deleted")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
