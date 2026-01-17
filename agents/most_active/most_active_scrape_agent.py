#!/usr/bin/env python3
"""
Scrape Yahoo Finance Most Active (first page: 25 rows) and store into SQLite
URL: https://finance.yahoo.com/markets/stocks/most-active/

Creates SQLite DB with table columns named exactly like Yahoo headers (quoted identifiers).
Only includes stocks with positive or zero change (excludes negative change).
Excludes stocks that are already in the top_gainers table.
"""

import json
import re
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# Import config to get database path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.config import Config
from core.database import connect

YAHOO_MOST_ACTIVE_URL = "https://finance.yahoo.com/markets/stocks/most-active/"
TABLE_NAME = "yahoo_most_active"
GAINERS_TABLE_NAME = "yahoo_top_gainers"

# Yahoo table headers we want to store (as displayed on the site)
# Note: Some headers are split across multiple lines/spans on the webpage
YAHOO_COLUMNS = [
    "Symbol",
    "Name",
    "Price",
    "Change",
    "Change %",
    "Volume",
    "Avg Vol (3M)",
    "Market Cap",
    "P/E Ratio (TTM)",
    "52 Wk Change %",
]

# We'll also add a scrape timestamp so you can track snapshots over time
EXTRA_COLUMNS = ["Scraped At (UTC)"]


def http_get(url: str) -> str:
    headers = {
        # A realistic UA helps avoid basic bot blocks
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-GB,en;q=0.9,en-US;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text


def find_embedded_json(html: str) -> dict:
    """
    Yahoo pages often embed a big JSON blob as:
      root.App.main = {...};
    We'll extract and parse it.
    """
    m = re.search(r"root\.App\.main\s*=\s*({.*?})\s*;\s*\n", html, flags=re.DOTALL)
    if not m:
        raise ValueError("Could not find root.App.main JSON in page HTML")

    raw = m.group(1)

    # Occasionally the JSON contains JS-style escaped sequences; json.loads usually handles it.
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        # Some pages include invalid sequences; attempt a small cleanup
        raw2 = raw.replace("\\x", "\\u00")
        data = json.loads(raw2)
    return data


def deep_find_rows(obj):
    """
    Walk nested dict/list to find a list of dicts that looks like screener rows.
    We look for a list where items contain 'symbol' or 'ticker' and some numeric fields.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("rows", "results") and isinstance(v, list) and v:
                if isinstance(v[0], dict) and ("symbol" in v[0] or "ticker" in v[0]):
                    return v
            found = deep_find_rows(v)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = deep_find_rows(item)
            if found is not None:
                return found
    return None


def normalize_from_json_rows(rows: list) -> list[dict]:
    """
    Convert Yahoo's JSON row objects into our YAHOO_COLUMNS keys.
    We attempt multiple possible field names because Yahoo changes them sometimes.
    """
    out = []
    for row in rows[:25]:
        # Common keys seen across Yahoo screeners:
        symbol = row.get("symbol") or row.get("ticker")
        name = row.get("shortName") or row.get("longName") or row.get("name")

        # Price fields
        price = (
            row.get("regularMarketPrice")
            or row.get("price")
            or row.get("lastPrice")
        )

        change = (
            row.get("regularMarketChange")
            or row.get("change")
        )

        pct_change = (
            row.get("regularMarketChangePercent")
            or row.get("percentChange")
            or row.get("changePercent")
        )

        volume = row.get("regularMarketVolume") or row.get("volume")
        avg_vol = row.get("averageDailyVolume3Month") or row.get("avgVolume3Month") or row.get("avgVol3m")
        market_cap = row.get("marketCap")
        pe_ttm = row.get("trailingPE") or row.get("peRatio") or row.get("peTTM")
        
        # 52 Week Change %
        # Calculate from 52 week high/low or get from Yahoo data
        fifty_two_wk_change = (
            row.get("fiftyTwoWeekChangePercent")
            or row.get("52WeekChangePercent")
            or row.get("52WeekChange")
        )
        # If not available, try to calculate from 52wk high/low and current price
        if fifty_two_wk_change is None:
            fifty_two_wk_high = row.get("fiftyTwoWeekHigh") or row.get("52WeekHigh")
            fifty_two_wk_low = row.get("fiftyTwoWeekLow") or row.get("52WeekLow")
            if fifty_two_wk_low and price:
                try:
                    # Calculate change from 52wk low
                    fifty_two_wk_change = ((float(price) - float(fifty_two_wk_low)) / float(fifty_two_wk_low)) * 100
                except (ValueError, TypeError):
                    fifty_two_wk_change = None

        out.append({
            "Symbol": symbol,
            "Name": name,
            "Price": price,
            "Change": change,
            "Change %": pct_change,
            "Volume": volume,
            "Avg Vol (3M)": avg_vol,
            "Market Cap": market_cap,
            "P/E Ratio (TTM)": pe_ttm,
            "52 Wk Change %": fifty_two_wk_change,
        })
    return out


def parse_html_table_fallback(html: str) -> list[dict]:
    """
    If JSON extraction fails, try parsing the visible HTML table.
    Handles multi-line headers where text is split across multiple spans.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        raise ValueError("No <table> found for fallback parsing")

    # Extract headers - combine text from all child elements (handles multi-line headers)
    headers = []
    for th in table.find_all("th"):
        # Get all text from th and its children, combine with space
        header_text = " ".join(th.stripped_strings)
        headers.append(header_text)
    
    # Build flexible index map - try exact match first, then partial matches
    idx = {}
    for col in YAHOO_COLUMNS:
        # Try exact match
        if col in headers:
            idx[col] = headers.index(col)
        else:
            # Try partial matches for multi-line headers
            # "P/E Ratio (TTM)" might be split as "P/E Ratio" and "(TTM)"
            # "52 Wk Change %" might be split as "52 Wk" and "Change %"
            found_idx = None
            for i, h in enumerate(headers):
                # Check if header contains key parts of our column name
                if col == "P/E Ratio (TTM)":
                    if "P/E" in h and "Ratio" in h and ("TTM" in h or "(TTM)" in h):
                        found_idx = i
                        break
                elif col == "52 Wk Change %":
                    if ("52" in h or "52 Wk" in h) and ("Change" in h or "Change %" in h):
                        found_idx = i
                        break
                elif col == "Change %":
                    if "Change" in h and "%" in h and "52" not in h:  # Exclude "52 Wk Change %"
                        found_idx = i
                        break
                elif col in h or h in col:
                    found_idx = i
                    break
            
            if found_idx is not None:
                idx[col] = found_idx
            else:
                # Last resort: try case-insensitive partial match
                col_lower = col.lower()
                for i, h in enumerate(headers):
                    if col_lower in h.lower() or h.lower() in col_lower:
                        idx[col] = i
                        break

    missing = [c for c in YAHOO_COLUMNS if c not in idx]
    if missing:
        # Log available headers for debugging
        print(f"[WARN] Available headers: {headers}", file=sys.stderr)
        raise ValueError(f"Fallback table is missing expected columns: {missing}")

    rows_out = []
    body_rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")[1:]
    
    # Check if Price, Change, and Change % are in the same column
    price_idx = idx.get("Price")
    change_idx = idx.get("Change")
    change_pct_idx = idx.get("Change %")
    combined_column = (price_idx == change_idx == change_pct_idx) and price_idx is not None
    
    for tr in body_rows[:25]:
        tds = tr.find_all(["td", "th"])
        values = [td.get_text(" ", strip=True) for td in tds]
        
        row_dict = {}
        
        # If Price, Change, and Change % are in the same column, split them
        if combined_column and price_idx is not None and price_idx < len(values):
            combined_text = values[price_idx]
            
            # Pattern examples: "5.26 +1.33 (+33.70%)" or "$123.45 +1.23 +1.00%"
            # Extract: price (first number, may have $), change (second number with +/-), percentage (third with %)
            
            # Price is the first number (before any +/- signs)
            # Match: optional $, then digits with optional decimal, stop at first space or +/- sign
            price_match = re.search(r'[\$]?([\d,]+\.?\d*)', combined_text)
            price = price_match.group(1).replace(",", "") if price_match else None
            
            # Change is the number with +/- (but not in parentheses and not the percentage)
            # Look for pattern like "+1.33" or "-1.33" that's not inside parentheses
            change_match = re.search(r'([+-][\d,]+\.?\d*)(?![^(]*\))', combined_text)
            if not change_match:
                # Fallback: find first +/- number that's not a percentage
                change_match = re.search(r'([+-][\d,]+\.?\d*)(?!%)', combined_text)
            change = change_match.group(1).replace(",", "") if change_match else None
            
            # Percentage is the number with % (usually in parentheses like "(+33.70%)")
            pct_match = re.search(r'\(?([+-]?[\d,]+\.?\d*)%\)?', combined_text)
            change_pct = pct_match.group(1).replace(",", "") if pct_match else None
            
            row_dict["Price"] = price
            row_dict["Change"] = change
            row_dict["Change %"] = change_pct
        else:
            # They are in separate columns, but Price might still have combined text
            price_text = values[idx["Price"]] if "Price" in idx and idx["Price"] < len(values) else None
            if price_text:
                # Extract just the first number (price) from the text
                price_match = re.search(r'[\$]?([\d,]+\.?\d*)', price_text)
                row_dict["Price"] = price_match.group(1).replace(",", "") if price_match else price_text
            else:
                row_dict["Price"] = None
            
            row_dict["Change"] = values[idx["Change"]] if "Change" in idx and idx["Change"] < len(values) else None
            row_dict["Change %"] = values[idx["Change %"]] if "Change %" in idx and idx["Change %"] < len(values) else None
        
        # Fill in other columns
        for col in YAHOO_COLUMNS:
            if col not in row_dict:
                if col in idx and idx[col] < len(values):
                    row_dict[col] = values[idx[col]]
                else:
                    row_dict[col] = None
        
        rows_out.append(row_dict)

    return rows_out


def init_db(conn: sqlite3.Connection):
    cols = YAHOO_COLUMNS + EXTRA_COLUMNS

    # Quote identifiers so we can keep Yahoo-style names (spaces, %, parentheses)
    col_defs = []
    for c in cols:
        if c in ("Symbol", "Name", "Scraped At (UTC)"):
            col_defs.append(f'"{c}" TEXT')
        else:
            # Store numeric-ish fields as REAL; if strings come in, SQLite will still store them.
            col_defs.append(f'"{c}" REAL')

    # Use Symbol as primary key so we replace existing records for the same symbol
    sql = f"""
    CREATE TABLE IF NOT EXISTS "{TABLE_NAME}" (
        {", ".join(col_defs)},
        PRIMARY KEY ("Symbol")
    );
    """
    conn.execute(sql)
    conn.commit()


def get_existing_gainers_symbols(db_path: str) -> set:
    """Get all symbols from the top_gainers table."""
    conn = connect(db_path)
    try:
        cur = conn.execute(f'SELECT "Symbol" FROM "{GAINERS_TABLE_NAME}"')
        rows = cur.fetchall()
        return {row[0] for row in rows if row[0]}
    finally:
        conn.close()


def filter_rows(rows: list[dict], existing_gainers: set) -> list[dict]:
    """
    Filter rows to exclude:
    1. Stocks already in top_gainers table
    2. Stocks with negative change %
    """
    filtered = []
    for row in rows:
        symbol = row.get("Symbol")
        if not symbol:
            continue
        
        # Skip if already in top_gainers
        if symbol in existing_gainers:
            continue
        
        # Check change % - skip if negative
        change_pct = row.get("Change %")
        if change_pct is not None:
            try:
                # Try to parse as float
                change_val = float(str(change_pct).replace(",", "").replace("%", ""))
                if change_val < 0:
                    continue  # Skip negative changes
            except (ValueError, TypeError):
                # If we can't parse, check if it starts with "-"
                change_str = str(change_pct)
                if change_str.strip().startswith("-"):
                    continue  # Skip negative changes
        
        filtered.append(row)
    
    return filtered


def insert_rows(conn: sqlite3.Connection, rows: list[dict]):
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    cols = YAHOO_COLUMNS + EXTRA_COLUMNS
    placeholders = ", ".join(["?"] * len(cols))
    quoted_cols = ", ".join([f'"{c}"' for c in cols])

    sql = f'INSERT OR REPLACE INTO "{TABLE_NAME}" ({quoted_cols}) VALUES ({placeholders});'

    values_batch = []
    for r in rows:
        record = []
        for c in YAHOO_COLUMNS:
            record.append(r.get(c))
        record.append(scraped_at)
        values_batch.append(tuple(record))

    conn.executemany(sql, values_batch)
    conn.commit()
    return scraped_at


def main():
    # Get database path from config
    try:
        cfg = Config.from_env()
        db_path = cfg.sqlite_path
    except Exception as e:
        print(f"[ERROR] Failed to load config: {e}", file=sys.stderr)
        print("[ERROR] Using default database path: database/stock_analysis.db", file=sys.stderr)
        db_path = "database/stock_analysis.db"
    
    # Get existing gainers to exclude
    print("[INFO] Loading existing top gainers to exclude...")
    existing_gainers = get_existing_gainers_symbols(db_path)
    print(f"[INFO] Found {len(existing_gainers)} symbols in top_gainers to exclude")
    
    html = http_get(YAHOO_MOST_ACTIVE_URL)

    # Try JSON first
    rows = None
    try:
        data = find_embedded_json(html)
        candidate_rows = deep_find_rows(data)
        if not candidate_rows:
            raise ValueError("Could not locate screener rows in embedded JSON")
        rows = normalize_from_json_rows(candidate_rows)

        # Basic sanity
        rows = [r for r in rows if r.get("Symbol")]
        if len(rows) < 10:
            raise ValueError("Too few rows extracted from JSON; likely blocked/changed")
    except Exception as e:
        print(f"[WARN] JSON extraction failed: {e}", file=sys.stderr)
        print("[WARN] Falling back to HTML table parsing...", file=sys.stderr)
        rows = parse_html_table_fallback(html)

    # Ensure first 25
    rows = rows[:25]
    
    # Filter rows: exclude gainers and negative changes
    print(f"[INFO] Filtering {len(rows)} rows...")
    filtered_rows = filter_rows(rows, existing_gainers)
    print(f"[INFO] After filtering: {len(filtered_rows)} rows (excluded {len(rows) - len(filtered_rows)})")

    # Ensure database directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    try:
        init_db(conn)
        scraped_at = insert_rows(conn, filtered_rows)
    finally:
        conn.close()

    print(f"Saved {len(filtered_rows)} rows into {db_path} table '{TABLE_NAME}' at {scraped_at} UTC")
    # Print first few for visibility
    for r in filtered_rows[:5]:
        print(r)


if __name__ == "__main__":
    main()
