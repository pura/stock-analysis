"""Twelve Data API tools."""
import requests
from typing import Any, Optional
import logging
import time

logger = logging.getLogger(__name__)

TWELVE_BASE = "https://api.twelvedata.com"


def fetch_time_series(
    api_key: str,
    symbol: str,
    interval: str,
    outputsize: int,
    retry_count: int = 3
) -> list[dict[str, Any]]:
    """
    Fetch time series data from Twelve Data.
    Returns bars ordered oldest to newest.
    """
    url = f"{TWELVE_BASE}/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": api_key,
    }
    
    for attempt in range(retry_count):
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            
            if "values" not in data:
                error_msg = data.get("message", "Unknown error")
                if "rate limit" in error_msg.lower() and attempt < retry_count - 1:
                    wait_time = (attempt + 1) * 2
                    logger.warning(f"Rate limit hit for {symbol}, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                logger.warning(f"API error for {symbol}: {error_msg}")
                return []
            
            vals = data["values"]
            if not vals:
                return []
            
            # Normalize to oldest->newest
            if len(vals) >= 2 and vals[0]["datetime"] > vals[-1]["datetime"]:
                vals = list(reversed(vals))
            
            return vals
            
        except requests.exceptions.RequestException as e:
            if attempt < retry_count - 1:
                wait_time = (attempt + 1) * 2
                logger.warning(f"Request error for {symbol}, retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            logger.error(f"Network error for {symbol}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error parsing response for {symbol}: {e}")
            return []
    
    return []


def fetch_rss_feed(rss_url: str, limit: int = 10) -> list[dict[str, Any]]:
    """Fetch news from an RSS feed URL."""
    import xml.etree.ElementTree as ET
    
    try:
        r = requests.get(rss_url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        r.raise_for_status()
        root = ET.fromstring(r.text)
        
        items = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            description = (item.findtext("description") or "").strip()
            source = (item.findtext("source") or "").strip()
            
            # Try to get source from different RSS formats
            if not source:
                source_elem = item.find("source")
                if source_elem is not None:
                    source = source_elem.text or source_elem.get("url", "")
            
            if title and link:
                items.append({
                    "title": title,
                    "url": link,
                    "published_at": pub_date,
                    "description": description,
                    "source": source or rss_url
                })
        
        return items
    except Exception as e:
        logger.warning(f"Error fetching RSS feed '{rss_url}': {e}")
        return []


def fetch_google_news(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Fetch news from Google News RSS (fallback method)."""
    from urllib.parse import quote_plus
    import xml.etree.ElementTree as ET
    
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-GB&gl=GB&ceid=GB:en"
    
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        
        items = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            source = (item.findtext("source") or "").strip()
            
            if title and link:
                items.append({
                    "title": title,
                    "url": link,
                    "published_at": pub_date,
                    "source": source or "Google News"
                })
        
        return items
    except Exception as e:
        logger.warning(f"Error fetching news for '{query}': {e}")
        return []


def load_news_sources() -> dict[str, Any]:
    """Load predefined news sources from JSON file."""
    import json
    from pathlib import Path
    
    sources_path = Path("data/news_sources.json")
    if not sources_path.exists():
        logger.warning(f"News sources file not found: {sources_path}")
        return {
            "financial_news_sites": [],
            "stock_specific_sources": {},
            "sector_sources": {},
            "macro_economic_sources": []
        }
    
    try:
        with open(sources_path) as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading news sources: {e}")
        return {
            "financial_news_sites": [],
            "stock_specific_sources": {},
            "sector_sources": {},
            "macro_economic_sources": []
        }


def load_company_names() -> dict[str, dict]:
    """Load company name mappings from JSON file."""
    import json
    from pathlib import Path
    
    names_path = Path("data/company_names.json")
    if not names_path.exists():
        logger.warning(f"Company names file not found: {names_path}")
        return {}
    
    try:
        with open(names_path) as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading company names: {e}")
        return {}


def matches_symbol(item: dict, symbol: str) -> bool:
    """Check if news item matches the stock symbol by company name."""
    if not symbol:
        return True
    
    company_names = load_company_names()
    symbol_upper = symbol.upper()
    
    # Get company name and aliases
    company_info = company_names.get(symbol_upper, {})
    company_name = company_info.get("name", "")
    aliases = company_info.get("aliases", [])
    
    title = (item.get("title", "") or "").lower()
    description = (item.get("description", "") or "").lower()
    text = f"{title} {description}"
    
    # Check for symbol itself (some articles might mention it)
    symbol_clean = symbol.replace(".L", "").upper()
    if symbol_clean.lower() in text or symbol_upper.lower() in text:
        return True
    
    # Check for company name
    if company_name and company_name.lower() in text:
        return True
    
    # Check for aliases
    for alias in aliases:
        if alias.lower() in text:
            return True
    
    return False


def date_in_range(date_str: str, target_date: str, days_before: int = 2, days_after: int = 2) -> bool:
    """Check if a date string falls within a range around target date."""
    from datetime import datetime, timedelta
    
    try:
        # Parse target date
        target = datetime.strptime(target_date, "%Y-%m-%d")
        date_lower = target - timedelta(days=days_before)
        date_upper = target + timedelta(days=days_after)
        
        # Try to parse the date string (could be various formats)
        date_to_check = None
        for fmt in ["%Y-%m-%d", "%a, %d %b %Y", "%d %b %Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
            try:
                date_to_check = datetime.strptime(date_str[:19], fmt)
                break
            except (ValueError, IndexError):
                continue
        
        if date_to_check is None:
            # If we can't parse, check if the date string contains the target date
            return target_date in date_str
        
        return date_lower.date() <= date_to_check.date() <= date_upper.date()
    except Exception:
        # If parsing fails, check if target date is in the string
        return target_date in date_str


def fetch_news_from_sources(
    symbol: Optional[str] = None,
    sector: Optional[str] = None,
    date_filter: Optional[str] = None,
    date_range_days: int = 2,
    limit_per_source: int = 5,
    require_symbol_match: bool = True
) -> list[dict[str, Any]]:
    """
    Fetch news from predefined sources.
    
    Args:
        symbol: Stock symbol (e.g., "AAPL") - REQUIRED if require_symbol_match=True
        sector: Sector name (e.g., "Technology")
        date_filter: Date string to filter by (YYYY-MM-DD) - center date
        date_range_days: Number of days before/after date_filter to include (default: 2)
        limit_per_source: Maximum items per source
        require_symbol_match: Only return news that mentions the symbol
    
    Returns:
        List of news items from all relevant sources (filtered by symbol if required)
    """
    if require_symbol_match and not symbol:
        logger.warning("Symbol required when require_symbol_match=True")
        return []
    
    sources_config = load_news_sources()
    all_items = []
    
    # Fetch from stock-specific sources first (most relevant)
    if symbol and symbol in sources_config.get("stock_specific_sources", {}):
        for source in sources_config["stock_specific_sources"][symbol]:
            try:
                items = fetch_rss_feed(source["rss_url"], limit=limit_per_source * 2)
                for item in items:
                    item["source_name"] = source["name"]
                    item["source_type"] = source["type"]
                    # Filter by date range if provided
                    if date_filter:
                        pub_date = item.get("published_at", "")
                        if not date_in_range(pub_date, date_filter, date_range_days, date_range_days):
                            continue
                    # Filter by symbol match
                    if require_symbol_match and not matches_symbol(item, symbol):
                        continue
                    all_items.append(item)
                time.sleep(0.3)
            except Exception as e:
                logger.warning(f"Error fetching from {source['name']}: {e}")
    
    # Fetch from sector-specific sources (if symbol matches)
    if sector and sector in sources_config.get("sector_sources", {}):
        for source in sources_config["sector_sources"][sector]:
            try:
                items = fetch_rss_feed(source["rss_url"], limit=limit_per_source * 2)
                for item in items:
                    item["source_name"] = source["name"]
                    item["source_type"] = source["type"]
                    # Filter by date range if provided
                    if date_filter:
                        pub_date = item.get("published_at", "")
                        if not date_in_range(pub_date, date_filter, date_range_days, date_range_days):
                            continue
                    # Filter by symbol match
                    if require_symbol_match and symbol and not matches_symbol(item, symbol):
                        continue
                    all_items.append(item)
                time.sleep(0.3)
            except Exception as e:
                logger.warning(f"Error fetching from {source['name']}: {e}")
    
    # Only fetch from general financial news sites if we need more results
    # AND we're not requiring strict symbol matching (or if symbol is provided, filter strictly)
    if not require_symbol_match or len(all_items) < limit_per_source:
        for source in sources_config.get("financial_news_sites", []):
            try:
                items = fetch_rss_feed(source["rss_url"], limit=limit_per_source * 2)
                for item in items:
                    item["source_name"] = source["name"]
                    item["source_type"] = source["type"]
                    # Filter by date range if provided
                    if date_filter:
                        pub_date = item.get("published_at", "")
                        if not date_in_range(pub_date, date_filter, date_range_days, date_range_days):
                            continue
                    # Filter by symbol match if required
                    if require_symbol_match and symbol and not matches_symbol(item, symbol):
                        continue
                    all_items.append(item)
                time.sleep(0.3)  # Rate limiting
            except Exception as e:
                logger.warning(f"Error fetching from {source['name']}: {e}")
    
    # ALWAYS fetch from macro-economic sources (diseases, wars, economic events)
    # These affect all stocks even if they don't mention the company
    # Mark them with special type so they're included for all stocks
    for source in sources_config.get("macro_economic_sources", []):
        try:
            items = fetch_rss_feed(source["rss_url"], limit=limit_per_source)
            for item in items:
                item["source_name"] = source["name"]
                item["source_type"] = "macro_global"  # Special type for global events
                item["applies_to_all_stocks"] = True  # Flag to indicate this applies to all stocks
                # Filter by date range if provided
                if date_filter:
                    pub_date = item.get("published_at", "")
                    if not date_in_range(pub_date, date_filter, date_range_days, date_range_days):
                        continue
                all_items.append(item)
            time.sleep(0.3)
        except Exception as e:
            logger.warning(f"Error fetching from {source['name']}: {e}")
    
    # Deduplicate by URL
    seen_urls = set()
    unique_items = []
    for item in all_items:
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_items.append(item)
    
    return unique_items
