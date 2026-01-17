"""
Most Active Cleanup Agent

Archives old records from yahoo_most_active, yahoo_most_active_trend, and yahoo_most_active_trades 
tables to archive tables, then deletes them from the main tables.
Keeps only records from today in the main tables.
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

MOST_ACTIVE_TABLE_NAME = "yahoo_most_active"
TREND_TABLE_NAME = "yahoo_most_active_trend"
TRADES_TABLE_NAME = "yahoo_most_active_trades"

MOST_ACTIVE_ARCHIVE_TABLE = "yahoo_most_active_archive"
TREND_ARCHIVE_TABLE = "yahoo_most_active_trend_archive"
TRADES_ARCHIVE_TABLE = "yahoo_most_active_trades_archive"


def init_archive_table(conn, table_name: str, source_table_name: str):
    """Initialize archive table with same structure as source table, plus archived_at column."""
    # Check if archive table already exists
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    table_exists = cur.fetchone() is not None
    
    if table_exists:
        # Check if archived_at column exists
        cur = conn.execute(f"PRAGMA table_info('{table_name}')")
        columns = [col[1] for col in cur.fetchall()]
        if 'archived_at' not in columns:
            # Add archived_at column to existing table
            logger.info(f"Adding archived_at column to existing {table_name}")
            conn.execute(f'ALTER TABLE "{table_name}" ADD COLUMN archived_at TEXT NOT NULL DEFAULT (datetime(\'now\'))')
            conn.commit()
        return
    
    # Get the CREATE TABLE statement from source table
    cur = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (source_table_name,)
    )
    result = cur.fetchone()
    
    if not result:
        logger.warning(f"Source table {source_table_name} not found, skipping archive table creation")
        return
    
    # Modify the CREATE TABLE statement to add archived_at column
    create_sql = result[0]
    # Remove the closing parenthesis and add archived_at column
    if create_sql.endswith(');'):
        create_sql = create_sql[:-2] + ', archived_at TEXT NOT NULL DEFAULT (datetime(\'now\')));'
    else:
        create_sql = create_sql.replace(');', ', archived_at TEXT NOT NULL DEFAULT (datetime(\'now\')));')
    
    # Replace table name - handle both quoted and unquoted table names
    create_sql = create_sql.replace(f'CREATE TABLE "{source_table_name}"', f'CREATE TABLE "{table_name}"')
    create_sql = create_sql.replace(f'CREATE TABLE {source_table_name}', f'CREATE TABLE "{table_name}"')
    # Also handle IF NOT EXISTS case
    create_sql = create_sql.replace(f'CREATE TABLE IF NOT EXISTS "{source_table_name}"', f'CREATE TABLE IF NOT EXISTS "{table_name}"')
    create_sql = create_sql.replace(f'CREATE TABLE IF NOT EXISTS {source_table_name}', f'CREATE TABLE IF NOT EXISTS "{table_name}"')
    
    conn.execute(create_sql)
    conn.commit()
    logger.info(f"Created archive table {table_name}")


def archive_and_cleanup_most_active_table(db_path: str, today_str: str) -> int:
    """Archive and clean up old records from yahoo_most_active table."""
    conn = connect(db_path)
    try:
        # Initialize archive table
        init_archive_table(conn, MOST_ACTIVE_ARCHIVE_TABLE, MOST_ACTIVE_TABLE_NAME)
        
        # Get column names from source table (excluding any auto-increment primary key)
        cur = conn.execute(f"PRAGMA table_info('{MOST_ACTIVE_TABLE_NAME}')")
        columns = [col[1] for col in cur.fetchall()]
        col_list = ', '.join([f'"{col}"' for col in columns])
        
        # Archive old records (copy to archive table)
        archived_count = conn.execute(
            f'''
            INSERT INTO "{MOST_ACTIVE_ARCHIVE_TABLE}" ({col_list}, archived_at)
            SELECT {col_list}, datetime('now')
            FROM "{MOST_ACTIVE_TABLE_NAME}"
            WHERE date(substr("Scraped At (UTC)", 1, 10)) != date(?)
            ''',
            (today_str,)
        ).rowcount
        
        # Delete archived records from main table
        deleted_count = conn.execute(
            f'''
            DELETE FROM "{MOST_ACTIVE_TABLE_NAME}"
            WHERE date(substr("Scraped At (UTC)", 1, 10)) != date(?)
            ''',
            (today_str,)
        ).rowcount
        
        conn.commit()
        
        # Get remaining count
        cur = conn.execute(f'SELECT COUNT(*) FROM "{MOST_ACTIVE_TABLE_NAME}"')
        remaining_count = cur.fetchone()[0]
        logger.info(f"  {MOST_ACTIVE_TABLE_NAME}: Archived {archived_count} records, deleted {deleted_count}, {remaining_count} remaining")
        
        return deleted_count
    except Exception as e:
        logger.error(f"Error archiving/cleaning {MOST_ACTIVE_TABLE_NAME}: {e}", exc_info=True)
        return 0
    finally:
        conn.close()


def archive_and_cleanup_trend_table(db_path: str, today_str: str) -> int:
    """Archive and clean up old records from yahoo_most_active_trend table."""
    conn = connect(db_path)
    try:
        # Initialize archive table
        init_archive_table(conn, TREND_ARCHIVE_TABLE, TREND_TABLE_NAME)
        
        # Get column names from source table
        cur = conn.execute(f"PRAGMA table_info('{TREND_TABLE_NAME}')")
        columns = [col[1] for col in cur.fetchall()]
        col_list = ', '.join([f'"{col}"' for col in columns])
        
        # Archive old records
        archived_count = conn.execute(
            f'''
            INSERT INTO "{TREND_ARCHIVE_TABLE}" ({col_list}, archived_at)
            SELECT {col_list}, datetime('now')
            FROM "{TREND_TABLE_NAME}"
            WHERE date(substr("Scraped At (UTC)", 1, 10)) != date(?)
            ''',
            (today_str,)
        ).rowcount
        
        # Delete archived records from main table
        deleted_count = conn.execute(
            f'''
            DELETE FROM "{TREND_TABLE_NAME}"
            WHERE date(substr("Scraped At (UTC)", 1, 10)) != date(?)
            ''',
            (today_str,)
        ).rowcount
        
        conn.commit()
        
        # Get remaining count
        cur = conn.execute(f'SELECT COUNT(*) FROM "{TREND_TABLE_NAME}"')
        remaining_count = cur.fetchone()[0]
        logger.info(f"  {TREND_TABLE_NAME}: Archived {archived_count} records, deleted {deleted_count}, {remaining_count} remaining")
        
        return deleted_count
    except Exception as e:
        logger.error(f"Error archiving/cleaning {TREND_TABLE_NAME}: {e}", exc_info=True)
        return 0
    finally:
        conn.close()


def archive_and_cleanup_trades_table(db_path: str, today_str: str) -> int:
    """Archive and clean up old records from yahoo_most_active_trades table."""
    conn = connect(db_path)
    try:
        # Initialize archive table
        init_archive_table(conn, TRADES_ARCHIVE_TABLE, TRADES_TABLE_NAME)
        
        # Get column names from source table
        cur = conn.execute(f"PRAGMA table_info('{TRADES_TABLE_NAME}')")
        columns = [col[1] for col in cur.fetchall()]
        col_list = ', '.join([f'"{col}"' for col in columns])
        
        # Archive old records
        archived_count = conn.execute(
            f'''
            INSERT INTO "{TRADES_ARCHIVE_TABLE}" ({col_list}, archived_at)
            SELECT {col_list}, datetime('now')
            FROM "{TRADES_TABLE_NAME}"
            WHERE date(substr(created_at, 1, 10)) != date(?)
            ''',
            (today_str,)
        ).rowcount
        
        # Delete archived records from main table
        deleted_count = conn.execute(
            f'''
            DELETE FROM "{TRADES_TABLE_NAME}"
            WHERE date(substr(created_at, 1, 10)) != date(?)
            ''',
            (today_str,)
        ).rowcount
        
        conn.commit()
        
        # Get remaining count
        cur = conn.execute(f'SELECT COUNT(*) FROM "{TRADES_TABLE_NAME}"')
        remaining_count = cur.fetchone()[0]
        logger.info(f"  {TRADES_TABLE_NAME}: Archived {archived_count} records, deleted {deleted_count}, {remaining_count} remaining")
        
        return deleted_count
    except Exception as e:
        logger.error(f"Error archiving/cleaning {TRADES_TABLE_NAME}: {e}", exc_info=True)
        return 0
    finally:
        conn.close()


def cleanup_old_records(db_path: str):
    """
    Archive and clean up old records from all most active tables.
    Archives all records EXCEPT those from today to archive tables,
    then deletes them from the main tables.
    Keeps only today's records in the main tables.
    """
    # Get today's date
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    
    logger.info(f"Cleanup: Archiving and keeping only records from today ({today_str})")
    logger.info("-" * 60)
    
    total_deleted = 0
    
    # Archive and cleanup most_active table
    deleted = archive_and_cleanup_most_active_table(db_path, today_str)
    total_deleted += deleted
    
    # Archive and cleanup trend table
    deleted = archive_and_cleanup_trend_table(db_path, today_str)
    total_deleted += deleted
    
    # Archive and cleanup trades table
    deleted = archive_and_cleanup_trades_table(db_path, today_str)
    total_deleted += deleted
    
    logger.info("-" * 60)
    logger.info(f"Total records archived and deleted: {total_deleted}")
    logger.info(f"Archive tables: {MOST_ACTIVE_ARCHIVE_TABLE}, {TREND_ARCHIVE_TABLE}, {TRADES_ARCHIVE_TABLE}")
    
    return total_deleted


def main():
    """Main entry point for cleanup agent."""
    setup_logging("INFO", "most_active_cleanup.log")
    
    try:
        cfg = Config.from_env()
        
        logger.info("="*60)
        logger.info("Most Active Cleanup Agent - Starting")
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
