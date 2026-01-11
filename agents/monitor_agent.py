"""Agent for intraday price monitoring and signal detection."""
import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import Config
from core.database import connect, store_signal, get_daily_ohlc, get_last_alert, update_alert_log
from core.signals import detect_signals
from core.tools import fetch_time_series
from utils.market_hours import get_today_date
from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


def get_day_open(symbol: str, conn, today: str) -> float:
    """Get today's opening price."""
    # Try to get from daily OHLC first
    daily = get_daily_ohlc(conn, symbol, today)
    if daily:
        return daily["open"]
    
    # Fallback: will need to get from intraday bars
    return 0.0


def should_alert(
    conn,
    symbol: str,
    signal: dict,
    current_price: float,
    min_gap_min: int,
    re_alert_step_pct: float,
    move_pct: float
) -> bool:
    """Check if alert should be sent based on throttling rules."""
    last_alert = get_last_alert(conn, symbol)
    
    if not last_alert or not last_alert.get("last_alert_at"):
        return True  # First alert
    
    # Check cooldown
    last_alert_time = datetime.fromisoformat(last_alert["last_alert_at"])
    gap_minutes = (datetime.utcnow() - last_alert_time).total_seconds() / 60
    
    if gap_minutes < min_gap_min:
        return False  # Still in cooldown
    
    # Check if direction flipped
    metrics = signal.get("metrics", {})
    direction = metrics.get("direction", "up" if metrics.get("pct_change", 0) > 0 else "down")
    last_direction = last_alert.get("last_alert_direction", "")
    
    if direction != last_direction:
        # Direction flipped, check if exceeds threshold
        pct_change = abs(metrics.get("pct_change", 0))
        if pct_change >= move_pct:
            return True
    
    # Check if price moved additional step %
    last_price = last_alert.get("last_alert_price", 0)
    if last_price > 0:
        price_change = abs((current_price - last_price) / last_price * 100)
        if price_change >= re_alert_step_pct:
            return True
    
    # Check severity increase
    current_severity = signal.get("severity", "medium")
    last_severity = last_alert.get("last_alert_severity", "medium")
    severity_levels = {"low": 1, "medium": 2, "high": 3}
    if severity_levels.get(current_severity, 0) > severity_levels.get(last_severity, 0):
        return True
    
    return False


def monitor_symbol(
    api_key: str,
    symbol: str,
    db_path: str,
    cfg: Config
) -> list[dict]:
    """Monitor one symbol and return detected signals."""
    conn = connect(db_path)
    try:
        # Fetch intraday bars (30min interval, last 50 bars)
        bars = fetch_time_series(api_key, symbol, "30min", 50)
        
        if not bars or len(bars) < 2:
            logger.warning(f"{symbol}: Insufficient intraday data")
            return []
        
        # Get today's open
        today = get_today_date()
        day_open = get_day_open(symbol, conn, today)
        
        # If no daily OHLC, try to get from first intraday bar of today
        if day_open == 0:
            today_bars = [b for b in bars if b.get("datetime", "").startswith(today)]
            if today_bars:
                day_open = float(today_bars[0].get("open", 0))
        
        if day_open == 0:
            logger.warning(f"{symbol}: Could not determine day open")
            return []
        
        # Detect signals
        signals = detect_signals(
            symbol,
            bars,
            day_open,
            cfg.move_pct,
            cfg.volume_spike_mult,
            cfg.breakout_lookback
        )
        
        if not signals:
            return []
        
        # Store signals and check throttling
        alertable_signals = []
        latest_price = float(bars[-1].get("close", 0))
        
        for signal in signals:
            signal_id = store_signal(
                conn,
                symbol,
                bars[-1].get("datetime", ""),
                signal["signal_type"],
                signal["metrics"],
                signal["severity"],
                signal.get("bar_id")
            )
            
            if signal_id and should_alert(conn, symbol, signal, latest_price,
                                         cfg.min_alert_gap_min, cfg.re_alert_step_pct, cfg.move_pct):
                alertable_signals.append({
                    "signal_id": signal_id,
                    "symbol": symbol,
                    "signal": signal,
                    "price": latest_price
                })
                # Update alert log
                direction = signal["metrics"].get("direction", "up" if signal["metrics"].get("pct_change", 0) > 0 else "down")
                update_alert_log(conn, symbol, latest_price, direction, signal["severity"])
        
        return alertable_signals
        
    except Exception as e:
        logger.error(f"Error monitoring {symbol}: {e}", exc_info=True)
        return []
    finally:
        conn.close()


def main():
    """Main entry point for monitor agent."""
    setup_logging("INFO", "monitor.log")
    
    try:
        cfg = Config.from_env()
        
        if not cfg.twelve_data_api_key:
            raise ValueError("TWELVE_DATA_API_KEY is required")
        
        from utils.market_hours import is_market_open
        
        if not is_market_open(cfg.market_open_hour, cfg.market_close_hour):
            logger.info("Market is closed, skipping monitoring")
            return
        
        logger.info(f"Monitoring {len(cfg.watchlist)} symbols...")
        
        all_signals = []
        for symbol in cfg.watchlist:
            try:
                signals = monitor_symbol(
                    cfg.twelve_data_api_key,
                    symbol,
                    cfg.sqlite_path,
                    cfg
                )
                all_signals.extend(signals)
                import time
                time.sleep(0.5)  # Be polite
            except Exception as e:
                logger.error(f"Failed to monitor {symbol}: {e}")
        
        logger.info(f"Detected {len(all_signals)} alertable signals")
        return all_signals
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
