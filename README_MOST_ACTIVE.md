# Most Active Stock Trading System

An automated stock trading system that scrapes most active stocks from Yahoo Finance, analyzes price trends, and generates buy/sell signals using Twelve Data API.

## Features

- **Most Active Scraping**: Automatically scrapes most active stocks from Yahoo Finance (filters out stocks already in top gainers and negative changes)
- **Trend Analysis**: Analyzes intraday price trends using linear regression slope calculation
- **Trade Signals**: Generates clear BUY/SELL signals based on trend analysis and position tracking
- **Data Archiving**: Automatically archives old data while keeping today's data active
- **Rate Limit Handling**: Smart batching and waiting to respect API rate limits

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Get API Key

- Sign up at [Twelve Data](https://twelvedata.com/pricing)
- Get your free API key (8 API credits per minute on free tier)

### 3. Configure Environment

Create a `.env` file:

```bash
# Twelve Data API
TWELVE_DATA_API_KEY=your_api_key_here

# Database (stored in database/ folder)
SQLITE_PATH=database/stock_analysis.db

# Logging
LOG_LEVEL=INFO
```

### 4. Run the Pipeline

**Manual run:**
```bash
python3 -m runner.run_most_active_pipeline
```

**Run individual agents:**
```bash
# Scrape most active stocks
python3 -m agents.most_active.most_active_scrape_agent

# Analyze trends
python3 -m agents.most_active.most_active_trend_agent

# Generate trade signals
python3 -m agents.most_active.most_active_trade_agent

# Cleanup old data (keeps only today's data)
python3 -m agents.most_active.most_active_cleanup_agent
```

## How Each Agent Works

### 1. Most Active Scrape Agent (`most_active_scrape_agent.py`)

**What it does:**
- Scrapes Yahoo Finance's most active page (https://finance.yahoo.com/markets/stocks/most-active/)
- Extracts stocks with their details (Symbol, Name, Price, Change %, Volume, etc.)
- Filters out stocks that are already in top gainers table
- Filters out stocks with negative change percentages
- Stores data in `yahoo_most_active` table
- Updates existing records or inserts new ones based on Symbol

**Key features:**
- Runs every 5-30 minutes (via cron or manually)
- Handles HTML parsing and data extraction
- Smart filtering to avoid duplicates with top gainers
- Only includes stocks with positive changes

### 2. Most Active Trend Agent (`most_active_trend_agent.py`)

**What it does:**
- Reads latest most active stocks from database
- Fetches intraday price data (30-minute bars) from Twelve Data API
- Calculates price trends using linear regression slope analysis
- Determines if trend is "Up" or "Down" based on:
  - Slope of price trendline over last N bars
  - Open position status (if exists, checks if price dropped below buy price + 0.5%)
- Stores trend data in `yahoo_most_active_trend` table

**Key features:**
- Processes 5 symbols per batch with 62-second waits to avoid rate limits
- Uses mathematical trendline analysis (not just simple price comparison)
- Handles cases with few bars (2-3 bars use simple comparison, 4+ use regression)
- Falls back to Start Price vs Now comparison if insufficient intraday data
- Waits between DAILY and INTRADAY phases to prevent rate limit errors

### 3. Most Active Trade Agent (`most_active_trade_agent.py`)

**What it does:**
- Reads latest trend data from database
- Generates buy/sell signals:
  - **BUY**: If trend is "Up" and no open position exists → opens new position
  - **HOLD**: If trend is "Up" and position already open → keeps position open
  - **SELL**: If trend is "Down" and position is open → closes position
  - **NO ACTION**: If trend is "Down" and no position → does nothing
- Records all trades in `yahoo_most_active_trades` table
- Prints clear formatted table showing all symbols with their signals

**Key features:**
- Prevents duplicate buys (only opens position if one doesn't exist)
- Tracks profit/loss when closing positions
- Provides clear visual output with emojis (🟢 BUY, 🔴 SELL)
- Logs all signals to file for historical analysis

### 4. Most Active Cleanup Agent (`most_active_cleanup_agent.py`)

**What it does:**
- Archives old data from all most active tables to archive tables
- Deletes old records (anything not from today) from main tables
- Keeps only today's data in active tables for performance
- Preserves historical data in archive tables for analysis

**Key features:**
- Archives before deleting (data is preserved)
- Cleans three tables: `yahoo_most_active`, `yahoo_most_active_trend`, `yahoo_most_active_trades`
- Adds `archived_at` timestamp to track when data was archived
- Should run daily at 8 AM (before market opens)

## Automated Scheduling (Cron)

### Setup Cron Jobs

Edit your crontab:
```bash
crontab -e
```

### 1. Daily Cleanup (8:00 AM)

Runs cleanup agent every day at 8:00 AM to archive old data:

```bash
# Cleanup old data at 8 AM every day
0 8 * * * cd /Users/puraskarsapkota/Projects/Stock-Ayalyst && /usr/bin/python3 -m agents.most_active.most_active_cleanup_agent >> ~/most_active_cleanup.log 2>&1
```

### 2. Pipeline Runner (Every 30 Minutes During Market Hours)

Runs the complete pipeline every 30 minutes from market open (9:30 AM ET) to market close (4:00 PM ET), only on weekdays:

```bash
# Run pipeline every 30 minutes from 9:30 AM to 4:00 PM ET, weekdays only
30,0 9-16 * * 1-5 cd /Users/puraskarsapkota/Projects/Stock-Ayalyst && /usr/bin/python3 -m runner.run_most_active_pipeline >> ~/most_active_pipeline.log 2>&1
```

**Note:** Adjust the timezone in cron if your server is not in ET timezone. For example:
- **ET timezone**: `30,0 9-16 * * 1-5` (9:30 AM - 4:00 PM ET)
- **UTC timezone**: `30,0 14-21 * * 1-5` (9:30 AM - 4:00 PM ET = 2:30 PM - 9:00 PM UTC in winter)

### Alternative: Run Scrape Agent More Frequently

If you want to scrape more frequently (every 5 minutes) but run trend/trade analysis every 30 minutes:

```bash
# Scrape every 5 minutes during market hours
*/5 9-16 * * 1-5 cd /Users/puraskarsapkota/Projects/Stock-Ayalyst && /usr/bin/python3 -m agents.most_active.most_active_scrape_agent >> ~/most_active_scrape.log 2>&1

# Run trend + trade analysis every 30 minutes
30,0 9-16 * * 1-5 cd /Users/puraskarsapkota/Projects/Stock-Ayalyst && /usr/bin/python3 -m agents.most_active.most_active_trend_agent >> ~/most_active_trend.log 2>&1 && /usr/bin/python3 -m agents.most_active.most_active_trade_agent >> ~/most_active_trade.log 2>&1
```

## Pipeline Flow

```
1. Scrape Agent (every 5-30 mins)
   ↓
   Scrapes Yahoo Finance → Filters duplicates/negatives → Stores in yahoo_most_active table
   
2. Trend Agent (every 30 mins)
   ↓
   Reads most active → Fetches intraday data from Twelve Data → Calculates trends → Stores in yahoo_most_active_trend table
   
3. Trade Agent (every 30 mins)
   ↓
   Reads trends → Generates buy/sell signals → Records trades in yahoo_most_active_trades table → Prints signals
   
4. Cleanup Agent (daily at 8 AM)
   ↓
   Archives old data → Deletes from main tables → Keeps only today's data
```

## Database Tables

- **`yahoo_most_active`**: Current day's scraped most active stocks data
- **`yahoo_most_active_trend`**: Current day's trend analysis results
- **`yahoo_most_active_trades`**: All buy/sell trade records
- **`yahoo_most_active_archive`**: Archived historical most active data
- **`yahoo_most_active_trend_archive`**: Archived historical trend data
- **`yahoo_most_active_trades_archive`**: Archived historical trades

## Log Files

- `most_active_scrape.log` - Scrape agent logs
- `most_active_trend_twelvedata.log` - Trend agent logs
- `most_active_trade.log` - Trade agent logs
- `most_active_cleanup.log` - Cleanup agent logs
- `most_active_pipeline.log` - Pipeline runner logs

## Project Structure

```
Stock-Ayalyst/
├── agents/
│   └── most_active/
│       ├── most_active_scrape_agent.py   # Scrapes Yahoo Finance
│       ├── most_active_trend_agent.py     # Analyzes price trends
│       ├── most_active_trade_agent.py     # Generates buy/sell signals
│       └── most_active_cleanup_agent.py   # Archives old data
├── runner/
│   └── run_most_active_pipeline.py       # Runs all agents in sequence
├── core/
│   ├── config.py                          # Configuration management
│   └── database.py                        # Database operations
├── utils/
│   └── logging_config.py                  # Logging setup
├── database/
│   └── stock_analysis.db                  # SQLite database
├── requirements.txt
├── .env                                   # Environment variables
└── README_MOST_ACTIVE.md
```

## Differences from Top Gainers

The most active system is similar to top gainers but with key differences:

1. **Filtering**: Most active excludes stocks already in top gainers and stocks with negative changes
2. **Focus**: Targets stocks with high volume activity rather than just price gains
3. **Separate Tables**: Uses separate database tables to avoid conflicts with top gainers data
4. **Independent Trading**: Tracks positions separately from top gainers trades

## Troubleshooting

### Rate Limit Errors

If you see "run out of API credits" errors:
- The trend agent automatically waits 62 seconds between batches
- Each batch processes 5 symbols
- With 25 symbols, it takes ~10 minutes to complete

### No Trend Data

- Ensure scrape agent has run and populated `yahoo_most_active` table
- Check that Twelve Data API key is valid
- Verify market is open (trend agent needs intraday data)

### Database Issues

- Database is stored in `database/stock_analysis.db`
- Archive tables preserve historical data
- Cleanup agent runs daily to keep main tables clean

## License

MIT
