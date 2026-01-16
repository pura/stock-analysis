"""Agent for analyzing historical OHLC data and fetching news for significant price moves."""
import sys
import logging
import hashlib
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import Config
from core.database import (
    connect, 
    store_news_item, 
    link_ohlc_news,
    get_ohlc_with_news
)
from core.tools import fetch_google_news, fetch_news_from_sources, matches_symbol, date_in_range
from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


def hash_url(url: str) -> str:
    """Create hash for URL deduplication."""
    return hashlib.md5(url.encode()).hexdigest()


def calculate_daily_change(open_price: float, close_price: float) -> float:
    """Calculate daily price change percentage."""
    if open_price == 0:
        return 0.0
    return abs((close_price - open_price) / open_price) * 100.0


def format_date_for_news_query(date_str: str) -> str:
    """Format date string for news query (YYYY-MM-DD to 'MMM DD, YYYY' or similar)."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        # Google News works well with date ranges, so we'll use the date in query
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return date_str


def get_date_range_string(date_str: str, days_before: int = 2, days_after: int = 2) -> tuple[str, str]:
    """Get date range strings for query (start_date, end_date)."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        start_date = (dt - timedelta(days=days_before)).strftime("%Y-%m-%d")
        end_date = (dt + timedelta(days=days_after)).strftime("%Y-%m-%d")
        return start_date, end_date
    except Exception:
        return date_str, date_str


def fetch_news_for_date(
    symbol: str,
    date_str: str,
    sector: Optional[str],
    db_path: str,
    min_news_items: int = 5
) -> list[dict]:
    """Fetch and store news for a specific date and symbol."""
    news_items = []
    
    # Format date for query
    date_formatted = format_date_for_news_query(date_str)
    
    # First, try predefined news sources (RSS feeds from financial sites)
    # Fetch company-specific news AND global/macro events for the date range (±2 days)
    # News can be 1-2 days before or after the price change
    predefined_items = fetch_news_from_sources(
        symbol=symbol,
        sector=sector,
        date_filter=date_formatted,
        date_range_days=2,  # Look 2 days before and 2 days after
        limit_per_source=5,  # Get more items since we're looking at a date range
        require_symbol_match=False  # Get both company-specific AND global events
    )
    
    for item in predefined_items:
        # Include if:
        # 1. It matches the company name (company-specific news)
        # 2. OR it's a global/macro event (applies to all stocks)
        is_company_match = matches_symbol(item, symbol) if symbol else False
        is_global_event = item.get("applies_to_all_stocks", False)
        
        if is_company_match or is_global_event:
            url_hash = hash_url(item["url"])
            news_id = store_news_item(
                db_path,
                item["title"],
                item["url"],
                item.get("published_at"),
                item.get("source_name") or item.get("source", ""),
                f"predefined_{item.get('source_type', 'unknown')}",
                url_hash
            )
            
            if news_id:
                link_ohlc_news(db_path, symbol, date_str, news_id, "historical")
                news_items.append({
                    "id": news_id,
                    "title": item["title"],
                    "url": item["url"],
                    "published_at": item.get("published_at"),
                    "source": item.get("source_name") or item.get("source", "")
                })
    
    # Fallback: Build queries with date range context for Google News
    # Include date range in query to get news from ±2 days
    if len(news_items) < min_news_items:
        start_date, end_date = get_date_range_string(date_str, days_before=2, days_after=2)
        queries = [
            f"{symbol} stock {start_date}..{end_date}",
            f"{symbol} news {start_date}..{end_date}",
            f"{symbol} {date_formatted}",
        ]
        
        # Add sector-specific queries if available
        if sector:
            queries.append(f"{sector} {symbol} {start_date}..{end_date}")
        
        for query in queries:
            try:
                items = fetch_google_news(query, limit=5)
                for item in items:
                    # Check if item is within date range (±2 days)
                    pub_date = item.get("published_at", "")
                    if not date_in_range(pub_date, date_str, days_before=2, days_after=2):
                        continue
                    
                    url_hash = hash_url(item["url"])
                    news_id = store_news_item(
                        db_path,
                        item["title"],
                        item["url"],
                        item.get("published_at"),
                        item.get("source"),
                        query,
                        url_hash
                    )
                    
                    if news_id:
                        # Link news to OHLC record
                        link_ohlc_news(db_path, symbol, date_str, news_id, "historical")
                        news_items.append({
                            "id": news_id,
                            "title": item["title"],
                            "url": item["url"],
                            "published_at": item.get("published_at"),
                            "source": item.get("source")
                        })
                
                # Be polite to Google News API
                time.sleep(0.5)
                
                if len(news_items) >= min_news_items:
                    break
            except Exception as e:
                logger.warning(f"Error fetching news for query '{query}': {e}")
                continue
    
    return news_items


def analyze_historical_data(
    db_path: str,
    min_change_pct: float = 5.0,
    symbols: Optional[list[str]] = None,
    sector_map: Optional[dict[str, str]] = None
) -> dict[str, Any]:
    """Analyze historical OHLC data and fetch news for significant moves."""
    logger.info(f"Starting historical news analysis (min change: {min_change_pct}%)")
    
    conn = connect(db_path)
    stats = {
        "total_records": 0,
        "significant_moves": 0,
        "news_fetched": 0,
        "symbols_processed": set(),
        "errors": []
    }
    
    try:
        # Query all OHLC records
        query = """
            SELECT symbol, date, open, close, 
                   ABS((close - open) / open * 100) as change_pct
            FROM stock_history
            WHERE ABS((close - open) / open * 100) >= ?
        """
        params = [min_change_pct]
        
        if symbols:
            placeholders = ",".join(["?"] * len(symbols))
            query += f" AND symbol IN ({placeholders})"
            params.extend(symbols)
        
        query += " ORDER BY symbol, date DESC"
        
        cur = conn.execute(query, params)
        rows = cur.fetchall()
        
        stats["total_records"] = len(rows)
        logger.info(f"Found {len(rows)} records with >= {min_change_pct}% daily change")
        
        # Process each significant move
        for row in rows:
            symbol = row[0]
            date_str = row[1]
            open_price = row[2]
            close_price = row[3]
            change_pct = row[4]
            
            stats["symbols_processed"].add(symbol)
            
            # Check if news already exists for this date
            existing = get_ohlc_with_news(db_path, symbol=symbol, min_change_pct=None)
            has_news = any(
                item["date"] == date_str and item["news"] 
                for item in existing
            )
            
            if has_news:
                logger.debug(f"{symbol} {date_str}: News already exists, skipping")
                continue
            
            try:
                sector = sector_map.get(symbol) if sector_map else None
                logger.info(
                    f"{symbol} {date_str}: {change_pct:.2f}% change "
                    f"(open: {open_price:.2f}, close: {close_price:.2f})"
                )
                
                news_items = fetch_news_for_date(
                    symbol,
                    date_str,
                    sector,
                    db_path
                )
                
                if news_items:
                    stats["news_fetched"] += len(news_items)
                    stats["significant_moves"] += 1
                    logger.info(
                        f"{symbol} {date_str}: Fetched {len(news_items)} news items"
                    )
                else:
                    logger.warning(f"{symbol} {date_str}: No news found")
                
                # Rate limiting
                time.sleep(1)
                
            except Exception as e:
                error_msg = f"{symbol} {date_str}: {e}"
                stats["errors"].append(error_msg)
                logger.error(error_msg, exc_info=True)
                continue
        
        stats["symbols_processed"] = list(stats["symbols_processed"])
        
    finally:
        conn.close()
    
    return stats


def main():
    """Main entry point for historical news agent."""
    setup_logging("INFO", "historical_news.log")
    
    try:
        cfg = Config.from_env()
        
        # Get symbols from watchlist or all symbols in database
        symbols = cfg.watchlist
        
        logger.info("="*60)
        logger.info("Historical News Analysis Agent")
        logger.info(f"Symbols: {', '.join(symbols)}")
        logger.info(f"Min change threshold: 5.0%")
        logger.info("="*60)
        
        stats = analyze_historical_data(
            cfg.sqlite_path,
            min_change_pct=5.0,
            symbols=symbols,
            sector_map=cfg.sector_map
        )
        
        logger.info("="*60)
        logger.info("Analysis Complete")
        logger.info(f"Total records analyzed: {stats['total_records']}")
        logger.info(f"Significant moves processed: {stats['significant_moves']}")
        logger.info(f"News items fetched: {stats['news_fetched']}")
        logger.info(f"Symbols processed: {len(stats['symbols_processed'])}")
        if stats["errors"]:
            logger.warning(f"Errors encountered: {len(stats['errors'])}")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
