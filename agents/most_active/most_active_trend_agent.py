"""
Most Active Trend Agent (Twelve Data)

Requirements:
  pip install requests

Assumes:
  - core.database.connect(db_path) -> sqlite3.Connection
  - core.config.Config.from_env() provides:
      - cfg.sqlite_path
      - cfg.twelve_data_api_key
"""

import sys
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from math import fsum

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests

from core.config import Config
from core.database import connect
from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)

TABLE_NAME = "yahoo_most_active"
TREND_TABLE_NAME = "yahoo_most_active_trend"
TRADES_TABLE_NAME = "yahoo_most_active_trades"

TD_BASE = "https://api.twelvedata.com"

# US market time for "before 9:30 AM"
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = None  # fallback: we'll approximate with UTC offsets (less ideal)


# -------------------------
# DB helpers
# -------------------------

def init_trend_table(conn):
    sql = f"""
    CREATE TABLE IF NOT EXISTS "{TREND_TABLE_NAME}" (
        "Symbol" TEXT PRIMARY KEY,
        "Trend" TEXT NOT NULL,
        "Start Price" REAL,
        "2 hrs" REAL,
        "1.5 hrs" REAL,
        "1 hr" REAL,
        "30 mins" REAL,
        "Now" REAL,
        "Scraped At (UTC)" TEXT NOT NULL
    );
    """
    conn.execute(sql)
    conn.commit()


def get_latest_25_most_active(db_path: str) -> List[str]:
    """
    Reads exactly the latest 25 from yahoo_most_active by max "Scraped At (UTC)".
    """
    conn = connect(db_path)
    try:
        cur = conn.execute(f'SELECT MAX("Scraped At (UTC)") FROM "{TABLE_NAME}"')
        latest_ts = cur.fetchone()[0]
        if not latest_ts:
            return []

        cur = conn.execute(
            f'''
            SELECT "Symbol"
            FROM "{TABLE_NAME}"
            WHERE "Scraped At (UTC)" = ?
            ORDER BY "Symbol" ASC
            LIMIT 25
            ''',
            (latest_ts,),
        )
        return [r[0] for r in cur.fetchall() if r and r[0]]
    finally:
        conn.close()


def upsert_trend_rows(db_path: str, rows: List[Dict[str, object]]) -> None:
    conn = connect(db_path)
    try:
        init_trend_table(conn)
        sql = f'''
        INSERT OR REPLACE INTO "{TREND_TABLE_NAME}"
        ("Symbol", "Trend", "Start Price", "2 hrs", "1.5 hrs", "1 hr", "30 mins", "Now", "Scraped At (UTC)")
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        conn.executemany(
            sql,
            [
                (
                    r["Symbol"],
                    r["Trend"],
                    r.get("Start Price"),
                    r.get("2 hrs"),
                    r.get("1.5 hrs"),
                    r.get("1 hr"),
                    r.get("30 mins"),
                    r.get("Now"),
                    r["Scraped At (UTC)"],
                )
                for r in rows
            ],
        )
        conn.commit()
    finally:
        conn.close()


# -------------------------
# Time helpers
# -------------------------

def now_et(now_utc: datetime) -> datetime:
    if ET is not None:
        return now_utc.astimezone(ET)
    # fallback: approximate ET as UTC-5 (ignores DST)
    return (now_utc - timedelta(hours=5)).replace(tzinfo=None)


def before_market_open_930(et_dt: datetime) -> bool:
    """
    True if before 9:30am ET (same date).
    """
    # If ET has tzinfo, keep it; otherwise naive works too
    open_dt = et_dt.replace(hour=9, minute=30, second=0, microsecond=0)
    return et_dt < open_dt


def parse_td_dt(dt_str: str) -> Optional[datetime]:
    """
    Twelve Data datetime typically: "YYYY-MM-DD HH:MM:SS"
    (No tz). We interpret it as ET to align with US market time.
    """
    if not dt_str:
        return None
    try:
        d = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        if ET is not None:
            return d.replace(tzinfo=ET)
        return d  # naive ET approximation
    except Exception:
        return None


def safe_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


# -------------------------
# Twelve Data client
# -------------------------

class TwelveDataClient:
    def __init__(self, api_key: str, session: Optional[requests.Session] = None):
        self.api_key = api_key
        self.sess = session or requests.Session()

    def _get(self, path: str, params: Dict[str, str], timeout: int = 30) -> dict:
        url = f"{TD_BASE}{path}"
        params = dict(params)
        params["apikey"] = self.api_key

        # Retry with special handling for rate limits (429)
        for attempt in range(1, 4):
            try:
                r = self.sess.get(url, params=params, timeout=timeout)
                
                # Check for HTTP 429 (rate limit)
                if r.status_code == 429:
                    wait_seconds = 60  # Wait 1 minute for rate limit
                    logger.warning(f"Rate limit hit (429). Waiting {wait_seconds} seconds before retry {attempt}/3...")
                    time.sleep(wait_seconds)
                    continue  # Retry the request
                
                r.raise_for_status()
                data = r.json()

                # Twelve Data error format often includes {"status":"error","message":...}
                if isinstance(data, dict) and data.get("status") == "error":
                    error_code = data.get("code")
                    error_msg = data.get("message", "")
                    
                    # Check if it's a rate limit error (429 or message contains "credits")
                    if error_code == 429 or "credits" in error_msg.lower() or "limit" in error_msg.lower():
                        wait_seconds = 60  # Wait 1 minute for rate limit
                        if attempt < 3:
                            logger.warning(f"Rate limit error from API: {error_msg}. Waiting {wait_seconds} seconds before retry {attempt}/3...")
                            time.sleep(wait_seconds)
                            continue  # Retry the request
                        else:
                            raise RuntimeError(f"TwelveData rate limit error after retries: {error_msg} ({error_code})")
                    else:
                        raise RuntimeError(f"TwelveData error: {error_msg} ({error_code})")

                return data
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    wait_seconds = 60
                    if attempt < 3:
                        logger.warning(f"HTTP 429 rate limit. Waiting {wait_seconds} seconds before retry {attempt}/3...")
                        time.sleep(wait_seconds)
                        continue
                    else:
                        raise
                if attempt == 3:
                    raise
                sleep_s = 1.5 * attempt
                logger.debug(f"TwelveData GET retry {attempt}/3 after HTTP error: {e}. Sleeping {sleep_s}s")
                time.sleep(sleep_s)
            except Exception as e:
                if attempt == 3:
                    raise
                sleep_s = 1.5 * attempt
                logger.debug(f"TwelveData GET retry {attempt}/3 after error: {e}. Sleeping {sleep_s}s")
                time.sleep(sleep_s)

        raise RuntimeError("Unreachable")

    def time_series_batch(
        self,
        symbols: List[str],
        interval: str,
        outputsize: int,
        timezone_name: str = "America/New_York",
        order: str = "ASC",
    ) -> Dict[str, List[dict]]:
        """
        Returns: symbol -> list of bars (each bar dict has datetime/open/high/low/close/volume)
        Supports bulk (comma-separated symbol list).
        """
        sym_param = ",".join(symbols)
        data = self._get(
            "/time_series",
            {
                "symbol": sym_param,
                "interval": interval,
                "outputsize": str(outputsize),
                "timezone": timezone_name,
                "order": order,
            },
        )

        # Batch response format:
        # { "AAPL": { "meta":..., "values":[...] , "status":"ok" }, "MSFT": {...} }
        out: Dict[str, List[dict]] = {}
        if isinstance(data, dict) and "meta" in data and "values" in data:
            # single symbol returned
            out[symbols[0]] = data.get("values", []) or []
            return out

        for sym in symbols:
            node = data.get(sym)
            if not isinstance(node, dict):
                out[sym] = []
                continue
            if node.get("status") != "ok":
                out[sym] = []
                continue
            out[sym] = node.get("values", []) or []
        return out


# -------------------------
# Core logic
# -------------------------

def pick_close_at_or_before(bars: List[dict], target_et: datetime) -> Optional[float]:
    """
    bars are assumed in ascending order (oldest -> newest).
    returns close of the last bar whose datetime <= target.
    """
    best: Optional[float] = None
    for b in bars:
        dt = parse_td_dt(b.get("datetime", ""))
        if dt is None:
            continue
        if dt <= target_et:
            best = safe_float(b.get("close"))
        else:
            break
    return best


def compute_prices(
    bars_30m: List[dict],
    daily_bars: List[dict],
    now_utc: datetime,
) -> Dict[str, Optional[float]]:
    """
    Prices at:
      Start, 2 hrs, 1.5 hrs, 1 hr, 30 mins, Now
    If before 9:30am ET: fill missing with prev day's close (from daily bars).
    """
    et_dt = now_et(now_utc)

    # prev close: daily bars are ASC (oldest -> newest); take last bar close as "most recent close"
    prev_close = None
    if daily_bars:
        prev_close = safe_float(daily_bars[-1].get("close"))

    prices: Dict[str, Optional[float]] = {
        "Start Price": None,
        "2 hrs": None,
        "1.5 hrs": None,
        "1 hr": None,
        "30 mins": None,
        "Now": None,
    }

    # From intraday bars
    if bars_30m:
        # Start = first bar open (best proxy for today's open at 30m resolution)
        prices["Start Price"] = safe_float(bars_30m[0].get("open")) or safe_float(bars_30m[0].get("close"))
        # Now = latest bar close
        prices["Now"] = safe_float(bars_30m[-1].get("close"))

        targets = {
            "2 hrs": et_dt - timedelta(hours=2),
            "1.5 hrs": et_dt - timedelta(hours=1, minutes=30),
            "1 hr": et_dt - timedelta(hours=1),
            "30 mins": et_dt - timedelta(minutes=30),
        }
        for key, t in targets.items():
            prices[key] = pick_close_at_or_before(bars_30m, t)

    # Early-day fill rule
    if before_market_open_930(et_dt):
        for k in list(prices.keys()):
            if prices[k] is None:
                prices[k] = prev_close

    return prices


def _linear_regression_slope_and_r2(y: List[float]) -> Tuple[float, float]:
    """
    Simple OLS of y on x where x = 0..n-1.
    Returns (slope, r2).
    """
    n = len(y)
    if n < 2:
        return 0.0, 0.0

    x = list(range(n))
    x_mean = (n - 1) / 2.0
    y_mean = fsum(y) / n

    # Cov(x,y) and Var(x)
    num = 0.0
    den = 0.0
    for xi, yi in zip(x, y):
        dx = xi - x_mean
        dy = yi - y_mean
        num += dx * dy
        den += dx * dx

    if den == 0.0:
        return 0.0, 0.0

    slope = num / den
    intercept = y_mean - slope * x_mean

    # R^2
    ss_tot = 0.0
    ss_res = 0.0
    for xi, yi in zip(x, y):
        y_hat = intercept + slope * xi
        ss_tot += (yi - y_mean) ** 2
        ss_res += (yi - y_hat) ** 2

    r2 = 0.0 if ss_tot == 0.0 else 1.0 - (ss_res / ss_tot)
    return slope, r2


def compute_trend_from_slope(
    bars: List[Dict[str, object]],
    n: int = 10,
    min_abs_slope_pct_per_bar: float = 0.0,
    min_r2: float = 0.0,
) -> bool:
    """
    Calculates trend using the slope of a trendline over last N bars.
    Returns True if trend is UP, False otherwise.

    bars: list of dicts, each should contain at least {"close": "..."}.
          Assumes bars are in ascending time order (oldest -> newest).
    n: number of latest bars to use (if fewer exist, uses what is available).
    min_abs_slope_pct_per_bar: optional noise filter; require slope/avg_price >= this.
    min_r2: optional fit-quality filter; require r2 >= this.

    Note: slope is in "price units per bar". We convert to percent-per-bar vs avg price.
    With very few bars (1-3), uses simple price comparison instead of regression.
    """
    closes = []
    for b in bars:
        c = safe_float(b.get("close"))
        if c is not None:
            closes.append(c)

    if len(closes) < 1:
        return False  # no data => treat as not-up

    # If only 1 bar, can't determine trend
    if len(closes) == 1:
        return False

    # If 2 bars, use simple comparison
    if len(closes) == 2:
        return closes[1] > closes[0]

    # Use available bars (up to n)
    y = closes[-n:] if len(closes) > n else closes[:]
    num_bars = len(y)

    # For 3 bars, use simple comparison (regression with 3 points is less reliable)
    if num_bars == 3:
        return y[2] > y[0]  # latest > first

    # For 4+ bars, use linear regression
    slope, r2 = _linear_regression_slope_and_r2(y)

    avg_price = fsum(y) / len(y)
    if avg_price == 0:
        return False

    slope_pct_per_bar = slope / avg_price  # e.g. 0.001 == +0.1% per bar

    # Adjust filters based on number of bars (more lenient with fewer bars)
    # With 4-5 bars, R² can be less reliable, so lower the threshold
    adjusted_min_r2 = min_r2 if num_bars >= 6 else (min_r2 * 0.5 if num_bars >= 4 else 0.0)
    
    if r2 < adjusted_min_r2:
        return False

    if slope_pct_per_bar <= 0:
        return False

    # Adjust slope filter (more lenient with fewer bars)
    adjusted_min_slope = min_abs_slope_pct_per_bar if num_bars >= 6 else (min_abs_slope_pct_per_bar * 0.5 if num_bars >= 4 else 0.0)
    
    if slope_pct_per_bar < adjusted_min_slope:
        return False

    return True


def get_open_position_price(db_path: str, symbol: str) -> Optional[float]:
    """Get the buy_price of the most recent open position (buy without sale) for a symbol."""
    conn = connect(db_path)
    try:
        cur = conn.execute(
            f'''
            SELECT buy_price
            FROM "{TRADES_TABLE_NAME}"
            WHERE symbol = ? AND sale_price IS NULL AND sale_time IS NULL
            ORDER BY buy_time DESC
            LIMIT 1
            ''',
            (symbol,)
        )
        row = cur.fetchone()
        return safe_float(row[0]) if row and row[0] else None
    except Exception:
        # Table might not exist yet, return None
        return None
    finally:
        conn.close()


def determine_trend(
    bars_30m: List[dict],
    prices: Dict[str, Optional[float]],
    db_path: str,
    symbol: str,
    n: int = 10,
    min_abs_slope_pct_per_bar: float = 0.0002,
    min_r2: float = 0.15,
) -> str:
    """
    Determines trend based on:
    1. If open_position price exists:
       - If latest price < (trade price + 0.5%) => Down
       - Else if trend is up (from slope) => Up
       - Else => Down
    2. If open_position price does not exist:
       - If trend is up (from slope) => Up
       - Else => Down

    Trend is computed using slope over last N bars (or all available bars if fewer than N).
    Works with as few as 2 bars (uses simple comparison) or 4+ bars (uses linear regression).
    If insufficient intraday data (all prices same), falls back to Start Price vs Now comparison.
    """
    latest_price = prices.get("Now")
    start_price = prices.get("Start Price")
    
    if latest_price is None:
        return "Down"  # no price => conservative

    # Get open position price if exists
    trade_price = get_open_position_price(db_path, symbol)

    # Check if we have sufficient intraday data variation
    # If all historical prices are the same, bars might not have enough variation
    price_values = [prices.get("2 hrs"), prices.get("1.5 hrs"), prices.get("1 hr"), 
                   prices.get("30 mins"), prices.get("Now")]
    unique_prices = set([p for p in price_values if p is not None])
    has_price_variation = len(unique_prices) > 1
    
    # Calculate trend from slope if we have bars
    trend_up = False
    if bars_30m and len(bars_30m) > 1:
        trend_up = compute_trend_from_slope(
            bars_30m,
            n=n,
            min_abs_slope_pct_per_bar=min_abs_slope_pct_per_bar,
            min_r2=min_r2,
        )
    elif start_price is not None and latest_price is not None:
        # Fallback: if no bars or insufficient data, use Start vs Now comparison
        trend_up = latest_price > start_price
        logger.debug(f"{symbol}: Using fallback Start vs Now comparison (Start={start_price:.2f}, Now={latest_price:.2f})")

    if trade_price is not None:
        # Open position exists
        threshold = trade_price * (1.0 + 0.005)  # trade price + 0.5%
        if latest_price < threshold:
            return "Down"
        return "Up" if trend_up else "Down"
    else:
        # No open position
        return "Up" if trend_up else "Down"


def chunk(lst: List[str], n: int) -> List[List[str]]:
    return [lst[i:i+n] for i in range(0, len(lst), n)]


def process_most_active_trends(cfg: Config) -> None:
    symbols = get_latest_25_most_active(cfg.sqlite_path)
    if not symbols:
        logger.warning("No most active stocks found in database (latest snapshot empty).")
        return

    now_utc = datetime.now(timezone.utc)
    scraped_at = now_utc.isoformat(timespec="seconds")
    et_dt = now_et(now_utc)
    logger.info(f"Loaded {len(symbols)} symbols. Now (ET)={et_dt} | ScrapedAt(UTC)={scraped_at}")

    td = TwelveDataClient(cfg.twelve_data_api_key)

    # Twelve Data Basic plan is limited to 8 API credits per minute.
    # Each batch request uses credits, so we process 5 symbols at a time,
    # then wait 62 seconds to ensure we're within the rate limit.
    BATCH_SIZE = 5
    WAIT_BETWEEN_BATCHES = 62  # seconds - wait to avoid rate limits

    rows_to_store: List[Dict[str, object]] = []

    # 1) Fetch daily bars (outputsize=1) for prev close
    daily_map: Dict[str, List[dict]] = {}
    batches = list(chunk(symbols, BATCH_SIZE))
    total_batches = len(batches)
    
    logger.info(f"Starting DAILY data fetch for {len(symbols)} symbols in {total_batches} batches...")
    for i, batch in enumerate(batches, start=1):
        logger.info(f"Fetching DAILY (1day) for batch {i}/{total_batches}: {batch}")
        resp = td.time_series_batch(batch, interval="1day", outputsize=1, order="ASC")
        daily_map.update(resp)
        
        # Wait between batches (always wait, including after last batch before switching to INTRADAY)
        if i < total_batches:
            logger.info(f"Waiting {WAIT_BETWEEN_BATCHES} seconds before next DAILY batch to avoid rate limits...")
            time.sleep(WAIT_BETWEEN_BATCHES)
    
    # Wait before starting INTRADAY phase to ensure rate limit reset
    logger.info(f"DAILY data fetch completed. Waiting {WAIT_BETWEEN_BATCHES} seconds before starting INTRADAY data fetch...")
    time.sleep(WAIT_BETWEEN_BATCHES)

    # 2) Fetch intraday 30m bars (enough bars to cover 2 hours + buffer)
    intraday_map: Dict[str, List[dict]] = {}
    # outputsize 20 = 10 hours of 30m bars max; plenty
    
    logger.info(f"Starting INTRADAY data fetch for {len(symbols)} symbols in {total_batches} batches...")
    for i, batch in enumerate(batches, start=1):
        logger.info(f"Fetching INTRADAY (30min) for batch {i}/{total_batches}: {batch}")
        resp = td.time_series_batch(batch, interval="30min", outputsize=20, order="ASC")
        intraday_map.update(resp)
        
        # Wait between batches (except after the last one)
        if i < total_batches:
            logger.info(f"Waiting {WAIT_BETWEEN_BATCHES} seconds before next INTRADAY batch to avoid rate limits...")
            time.sleep(WAIT_BETWEEN_BATCHES)

    for i, sym in enumerate(symbols, start=1):
        try:
            bars_30m = intraday_map.get(sym, []) or []
            daily_bars = daily_map.get(sym, []) or []

            # Log bar count for debugging
            num_bars = len(bars_30m)
            if num_bars > 0:
                bar_closes = [safe_float(b.get("close")) for b in bars_30m if safe_float(b.get("close")) is not None]
                if len(bar_closes) >= 2:
                    first_close = bar_closes[0]
                    last_close = bar_closes[-1]
                    price_change = ((last_close - first_close) / first_close * 100) if first_close > 0 else 0
                    logger.debug(f"{sym}: {num_bars} bars, first_close={first_close:.2f}, last_close={last_close:.2f}, change={price_change:+.2f}%")
                else:
                    logger.debug(f"{sym}: {num_bars} bars, but only {len(bar_closes)} valid closes")
            else:
                logger.warning(f"{sym}: No intraday bars available")

            prices = compute_prices(bars_30m, daily_bars, now_utc)
            trend = determine_trend(bars_30m, prices, cfg.sqlite_path, sym)

            row = {
                "Symbol": sym,
                "Trend": trend,
                "Start Price": prices.get("Start Price"),
                "2 hrs": prices.get("2 hrs"),
                "1.5 hrs": prices.get("1.5 hrs"),
                "1 hr": prices.get("1 hr"),
                "30 mins": prices.get("30 mins"),
                "Now": prices.get("Now"),
                "Scraped At (UTC)": scraped_at,
            }
            rows_to_store.append(row)

            # Check if all historical prices are the same (indicates data issue)
            price_values = [prices.get("2 hrs"), prices.get("1.5 hrs"), prices.get("1 hr"), prices.get("30 mins"), prices.get("Now")]
            unique_prices = set([p for p in price_values if p is not None])
            if len(unique_prices) == 1 and num_bars > 1:
                logger.warning(f"{sym}: All historical prices are identical ({unique_prices.pop():.2f}) - may indicate insufficient intraday data")

            logger.info(
                f"[{i:02d}/{len(symbols)}] {sym} Trend={trend} "
                f"Start={row['Start Price']} 2hrs={row['2 hrs']} 1.5hrs={row['1.5 hrs']} "
                f"1hr={row['1 hr']} 30m={row['30 mins']} Now={row['Now']} (bars={num_bars})"
            )

        except Exception as e:
            logger.error(f"{sym}: Error processing: {e}", exc_info=True)

    if rows_to_store:
        upsert_trend_rows(cfg.sqlite_path, rows_to_store)
        logger.info(f"Stored {len(rows_to_store)} rows into {TREND_TABLE_NAME}.")


def main():
    setup_logging("INFO", "most_active_trend_twelvedata.log")
    try:
        cfg = Config.from_env()
        if not getattr(cfg, "twelve_data_api_key", None):
            raise RuntimeError("Missing Twelve Data API key: set TWELVE_DATA_API_KEY in your env/config.")
        process_most_active_trends(cfg)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
