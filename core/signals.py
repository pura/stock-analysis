"""Deterministic signal detection."""
from typing import Any
import math
import logging

logger = logging.getLogger(__name__)


def detect_signals(
    symbol: str,
    bars: list[dict[str, Any]],
    day_open: float,
    move_pct: float,
    volume_spike_mult: float,
    breakout_lookback: int
) -> list[dict[str, Any]]:
    """
    Detect signals from intraday bars.
    
    Args:
        symbol: Stock symbol
        bars: List of bars (oldest to newest)
        day_open: Today's opening price
        move_pct: Threshold for price move from open
        volume_spike_mult: Volume multiplier threshold
        breakout_lookback: Bars to look back for breakout
        
    Returns:
        List of signal dictionaries
    """
    if not bars or len(bars) < 2:
        return []
    
    signals = []
    latest = bars[-1]
    latest_close = _safe_float(latest.get("close"))
    latest_vol = _safe_float(latest.get("volume", 0), 0.0)
    latest_dt = latest.get("datetime", "")
    
    if math.isnan(latest_close) or day_open == 0:
        return []
    
    # Signal 1: Price change from day open
    pct_change_from_open = ((latest_close - day_open) / day_open) * 100.0
    if abs(pct_change_from_open) >= move_pct:
        signals.append({
            "signal_type": "move_from_open",
            "metrics": {
                "day_open": day_open,
                "latest_close": latest_close,
                "pct_change": pct_change_from_open,
                "direction": "up" if pct_change_from_open > 0 else "down"
            },
            "severity": "high" if abs(pct_change_from_open) >= move_pct * 2 else "medium",
            "bar_id": latest_dt
        })
    
    # Signal 2: Volume spike
    if len(bars) >= 21:
        window = bars[-21:-1]  # Last 20 bars excluding latest
        vols = [_safe_float(b.get("volume", 0), 0.0) for b in window]
        avg_vol = sum(vols) / len(vols) if vols else 0
        
        if avg_vol > 0 and latest_vol >= volume_spike_mult * avg_vol:
            signals.append({
                "signal_type": "volume_spike",
                "metrics": {
                    "latest_volume": latest_vol,
                    "avg_volume": avg_vol,
                    "multiplier": latest_vol / avg_vol
                },
                "severity": "medium",
                "bar_id": latest_dt
            })
    
    # Signal 3: Breakout/Breakdown
    if len(bars) >= breakout_lookback + 1:
        look = bars[-(breakout_lookback+1):-1]
        highs = [_safe_float(b.get("high")) for b in look]
        lows = [_safe_float(b.get("low")) for b in look]
        
        valid_highs = [h for h in highs if not math.isnan(h)]
        valid_lows = [l for l in lows if not math.isnan(l)]
        
        if valid_highs and valid_lows:
            prior_high = max(valid_highs)
            prior_low = min(valid_lows)
            
            if latest_close > prior_high:
                signals.append({
                    "signal_type": "breakout",
                    "metrics": {
                        "latest_close": latest_close,
                        "prior_high": prior_high,
                        "breakout_amount": latest_close - prior_high
                    },
                    "severity": "high",
                    "bar_id": latest_dt
                })
            elif latest_close < prior_low:
                signals.append({
                    "signal_type": "breakdown",
                    "metrics": {
                        "latest_close": latest_close,
                        "prior_low": prior_low,
                        "breakdown_amount": latest_close - prior_low
                    },
                    "severity": "high",
                    "bar_id": latest_dt
                })
    
    return signals


def _safe_float(x: Any, default: float = 0.0) -> float:
    """Safely convert to float."""
    if x is None:
        return default
    try:
        return float(x)
    except (ValueError, TypeError):
        return default
