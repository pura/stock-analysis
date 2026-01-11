"""Twelve Data API tools."""
import requests
from typing import Any
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


def fetch_google_news(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Fetch news from Google News RSS."""
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
                    "source": source
                })
        
        return items
    except Exception as e:
        logger.warning(f"Error fetching news for '{query}': {e}")
        return []
