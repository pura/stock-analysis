"""Configuration management."""
from dataclasses import dataclass
from typing import Optional, Any
import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _parse_float(key: str, default: float, min_val: Optional[float] = None) -> float:
    """Parse float from environment."""
    try:
        value = float(os.getenv(key, str(default)))
        if min_val is not None and value < min_val:
            raise ValueError(f"{key} must be >= {min_val}")
        return value
    except ValueError as e:
        raise ValueError(f"Invalid {key}: {e}")


def _parse_int(key: str, default: int, min_val: int = 1) -> int:
    """Parse int from environment."""
    try:
        value = int(os.getenv(key, str(default)))
        if value < min_val:
            raise ValueError(f"{key} must be >= {min_val}")
        return value
    except ValueError as e:
        raise ValueError(f"Invalid {key}: {e}")


@dataclass(frozen=True)
class Config:
    """Application configuration."""
    # API
    twelve_data_api_key: str
    
    # Watchlist
    watchlist: list[str]
    
    # Historical Data
    history_days: int  # Calendar days (default 365)
    
    # Signal Thresholds
    move_pct: float  # % change from day open
    volume_spike_mult: float
    breakout_lookback: int
    
    # Alert Throttling
    min_alert_gap_min: int  # Minutes between alerts
    re_alert_step_pct: float  # Additional % to re-alert
    
    # Market Hours (Europe/London)
    market_open_hour: int
    market_close_hour: int
    
    # Email
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    alert_email_to: str
    
    # Database
    sqlite_path: str  # Single database for all data
    
    # Logging
    log_level: str
    log_file: str
    
    # Sector Map
    sector_map: dict[str, str]
    
    # News Sources (optional, loaded from data/news_sources.json)
    news_sources: Optional[dict[str, Any]] = None
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment."""
        watchlist_str = os.getenv("WATCHLIST", "")
        if not watchlist_str.strip():
            raise ValueError("WATCHLIST is required")
        watchlist = [s.strip().upper() for s in watchlist_str.split(",") if s.strip()]
        
        # Load sector map
        sector_map_path = Path("data/sector_map.json")
        sector_map = {}
        if sector_map_path.exists():
            try:
                with open(sector_map_path) as f:
                    sector_map = json.load(f)
            except Exception:
                pass
        
        # Load news sources (optional)
        news_sources_path = Path("data/news_sources.json")
        news_sources = {}
        if news_sources_path.exists():
            try:
                with open(news_sources_path) as f:
                    news_sources = json.load(f)
            except Exception:
                pass
        
        return cls(
            twelve_data_api_key=os.getenv("TWELVE_DATA_API_KEY", ""),
            watchlist=watchlist,
            history_days=_parse_int("HISTORY_DAYS", 365, min_val=1),
            move_pct=_parse_float("MOVE_PCT", 1.5, min_val=0.0),
            volume_spike_mult=_parse_float("VOLUME_SPIKE_MULT", 2.0, min_val=0.0),
            breakout_lookback=_parse_int("BREAKOUT_LOOKBACK", 20, min_val=1),
            min_alert_gap_min=_parse_int("MIN_ALERT_GAP_MIN", 60, min_val=1),
            re_alert_step_pct=_parse_float("RE_ALERT_STEP_PCT", 0.5, min_val=0.0),
            market_open_hour=_parse_int("MARKET_OPEN_HOUR", 8, min_val=0),
            market_close_hour=_parse_int("MARKET_CLOSE_HOUR", 16, min_val=0),
            smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=_parse_int("SMTP_PORT", 587, min_val=1),
            smtp_user=os.getenv("SMTP_USER", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            alert_email_to=os.getenv("ALERT_EMAIL_TO", ""),
            sqlite_path=os.getenv("SQLITE_PATH", "database/stock_alerts.db"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=os.getenv("LOG_FILE", "stock_alerts.log"),
            sector_map=sector_map,
            news_sources=news_sources if news_sources else None,
        )
