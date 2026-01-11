"""Market hours utilities."""
from datetime import datetime
import pytz

LONDON_TZ = pytz.timezone("Europe/London")


def is_market_open(open_hour: int, close_hour: int) -> bool:
    """Check if market is currently open (Europe/London timezone)."""
    now = datetime.now(LONDON_TZ)
    current_hour = now.hour
    current_weekday = now.weekday()  # 0=Monday, 6=Sunday
    
    # Market closed on weekends
    if current_weekday >= 5:
        return False
    
    # Check if within market hours
    return open_hour <= current_hour < close_hour


def get_today_date() -> str:
    """Get today's date in YYYY-MM-DD format (London timezone)."""
    return datetime.now(LONDON_TZ).strftime("%Y-%m-%d")
