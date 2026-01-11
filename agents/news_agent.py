"""Agent for fetching news for triggered tickers."""
import sys
import logging
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import Optional, Any
from core.config import Config
from core.database import connect, store_news_item, link_signal_news
from core.tools import fetch_google_news
from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


def hash_url(url: str) -> str:
    """Create hash for URL deduplication."""
    return hashlib.md5(url.encode()).hexdigest()


def fetch_news_for_symbol(
    symbol: str,
    sector: Optional[str],
    db_path: str,
    signal_id: int
) -> dict[str, Any]:
    """Fetch and store news for a symbol."""
    conn = connect(db_path)
    try:
        news_items = {
            "direct": [],
            "sector_macro": [],
            "none_found": True
        }
        
        # Direct company queries
        queries = [
            f"{symbol} stock",
            f"{symbol} earnings",
            f"{symbol} news",
        ]
        
        for query in queries:
            items = fetch_google_news(query, limit=5)
            for item in items:
                url_hash = hash_url(item["url"])
                news_id = store_news_item(
                    conn,
                    item["title"],
                    item["url"],
                    item.get("published_at"),
                    item.get("source"),
                    query,
                    url_hash
                )
                if news_id:
                    link_signal_news(conn, signal_id, news_id, "direct")
                    news_items["direct"].append(item)
        
        # Sector query
        if sector:
            sector_query = f"{sector} sector {symbol}"
            items = fetch_google_news(sector_query, limit=3)
            for item in items:
                url_hash = hash_url(item["url"])
                news_id = store_news_item(
                    conn,
                    item["title"],
                    item["url"],
                    item.get("published_at"),
                    item.get("source"),
                    sector_query,
                    url_hash
                )
                if news_id:
                    link_signal_news(conn, signal_id, news_id, "sector_macro")
                    news_items["sector_macro"].append(item)
        
        # Macro queries
        macro_queries = [
            "Federal Reserve interest rates",
            "inflation CPI data",
            "oil price crude",
            "stock market index",
        ]
        
        for query in macro_queries:
            items = fetch_google_news(query, limit=2)
            for item in items:
                url_hash = hash_url(item["url"])
                news_id = store_news_item(
                    conn,
                    item["title"],
                    item["url"],
                    item.get("published_at"),
                    item.get("source"),
                    query,
                    url_hash
                )
                if news_id:
                    link_signal_news(conn, signal_id, news_id, "sector_macro")
                    news_items["sector_macro"].append(item)
        
        if news_items["direct"] or news_items["sector_macro"]:
            news_items["none_found"] = False
        else:
            # Store none_found marker
            link_signal_news(conn, signal_id, 0, "none_found")
        
        return news_items
        
    except Exception as e:
        logger.error(f"Error fetching news for {symbol}: {e}", exc_info=True)
        return {"direct": [], "sector_macro": [], "none_found": True}
    finally:
        conn.close()


def fetch_news_for_signals(
    signals: list[dict],
    cfg: Config,
    db_path: str
) -> dict[str, dict]:
    """Fetch news for all triggered signals."""
    logger.info(f"Fetching news for {len(signals)} signals...")
    
    news_by_symbol = {}
    
    for signal_data in signals:
        symbol = signal_data["symbol"]
        signal_id = signal_data["signal_id"]
        
        if symbol not in news_by_symbol:
            sector = cfg.sector_map.get(symbol)
            news_items = fetch_news_for_symbol(symbol, sector, db_path, signal_id)
            news_by_symbol[symbol] = news_items
        
        import time
        time.sleep(0.5)  # Be polite to Google News
    
    return news_by_symbol


if __name__ == "__main__":
    setup_logging("INFO", "news.log")
    # This is typically called from main.py, not directly
