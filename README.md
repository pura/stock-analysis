# Stock Alert System MVP

A low-noise stock monitoring system using CrewAI and Twelve Data API with deterministic signal detection and intelligent alert summarization.

## Features

- **Multi-market support**: US (AAPL, MSFT) and UK (BARC.L) tickers
- **Historical backfill**: Automatic 1-year daily OHLC data download
- **Intraday monitoring**: 30-minute interval price monitoring during market hours
- **Deterministic signals**: Price moves, volume spikes, breakouts/breakdowns
- **Noise control**: Smart throttling and cooldown mechanisms
- **News context**: Automatic news fetching for triggered tickers only
- **AI summarization**: CrewAI-powered alert generation
- **Email alerts**: Configurable email delivery

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Get API Key

- Sign up at [Twelve Data](https://twelvedata.com/pricing)
- Get your free API key (800 requests/day on free tier)

### 3. Configure Email

**For Gmail:**
1. Enable 2-Factor Authentication
2. Generate App Password: https://myaccount.google.com/apppasswords
3. Use App Password (not regular password) in `.env`

### 4. Create Configuration

```bash
cp .env.example .env
# Edit .env with your values
```

**Minimum required:**
```bash
TWELVE_DATA_API_KEY=your_key_here
WATCHLIST=AAPL,MSFT,GOOGL
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
ALERT_EMAIL_TO=alerts@example.com
```

### 5. Run Initial Backfill

```bash
python -m agents.backfill_agent
```

### 6. Test Monitoring

```bash
python main.py
```

### 7. Set Up Automation

See [QUICK_START.md](QUICK_START.md) for detailed cron/systemd setup.

## Detailed Setup

### Configure Environment

Create a `.env` file (see `.env.example` for template):

```bash
# Twelve Data API
TWELVE_DATA_API_KEY=your_api_key_here

# Watchlist (comma-separated, supports US and UK tickers)
WATCHLIST=AAPL,MSFT,GOOGL,BARC.L,TSCO.L

# Historical Data
HISTORY_DAYS=365  # Calendar days (default: 365, can use 252 for trading days)

# Signal Thresholds
MOVE_PCT=1.5  # Percentage change from day open to trigger
VOLUME_SPIKE_MULT=2.0  # Volume multiplier for spike detection
BREAKOUT_LOOKBACK=20  # Bars to look back for breakout/breakdown

# Alert Throttling
MIN_ALERT_GAP_MIN=60  # Minimum minutes between alerts for same symbol
RE_ALERT_STEP_PCT=0.5  # Additional % move to re-alert in same direction

# Market Hours (Europe/London timezone)
MARKET_OPEN_HOUR=8  # Market open hour (24h format)
MARKET_CLOSE_HOUR=16  # Market close hour (24h format)

# Email Configuration
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
ALERT_EMAIL_TO=alerts@example.com

# Database (stored in database/ folder)
SQLITE_PATH=database/stock_alerts.db

# Logging
LOG_LEVEL=INFO
LOG_FILE=stock_alerts.log
```

### 3. Sector Mapping (Optional)

Create `sector_map.json`:

```json
{
  "AAPL": "Technology",
  "MSFT": "Technology",
  "GOOGL": "Technology",
  "BARC.L": "Financial Services",
  "TSCO.L": "Consumer Goods"
}
```

### 4. Run Initial Backfill

```bash
python -m agents.backfill_agent
```

This downloads and stores 1 year of daily OHLC data for all tickers in your watchlist.

### 5. Start Monitoring

For development/testing:
```bash
python main.py
```

For production, use cron:

**Every 30 minutes during market hours:**
```bash
*/30 8-16 * * 1-5 cd /path/to/Stock-Ayalyst && /usr/bin/python3 main.py >> /var/log/stock_alerts.log 2>&1
```

**Daily end-of-day job (after market close):**
```bash
0 17 * * 1-5 cd /path/to/Stock-Ayalyst && /usr/bin/python3 -m agents.eod_agent >> /var/log/stock_alerts_eod.log 2>&1
```

## Project Structure

```
Stock-Ayalyst/
├── agents/
│   ├── __init__.py
│   ├── backfill_agent.py      # Historical OHLC backfill
│   ├── monitor_agent.py        # Intraday price monitoring
│   ├── news_agent.py           # News fetching for triggered tickers
│   ├── summarizer_agent.py    # CrewAI alert summarization
│   └── eod_agent.py            # End-of-day processing
├── core/
│   ├── __init__.py
│   ├── config.py               # Configuration management
│   ├── database.py             # Database schema and operations
│   ├── signals.py              # Deterministic signal detection
│   └── email.py                # Email delivery
├── utils/
│   ├── __init__.py
│   ├── market_hours.py         # Market hours utilities
│   └── logging_config.py      # Logging setup
├── data/
│   └── sector_map.json         # Sector mapping (optional)
├── main.py                     # Main monitoring entry point
├── requirements.txt
├── .env                        # Environment variables (create this)
└── README.md
```

## How It Works

1. **Backfill**: Downloads 1 year of daily OHLC data on first run
2. **Monitoring**: Every 30 minutes:
   - Fetches latest 30-min bars
   - Computes signals (price vs day open, volume, breakout)
   - Checks throttling rules
   - For triggered tickers: fetches news
   - Generates alert summary via CrewAI
   - Sends email if alerts exist
3. **End of Day**: Stores final daily OHLC and runs integrity checks

## Signal Types

- **move_from_open**: Price moved X% from today's opening price
- **volume_spike**: Volume exceeds average by multiplier
- **breakout**: Price breaks above N-bar high
- **breakdown**: Price breaks below N-bar low

## Alert Throttling

- No duplicate alerts for same symbol+signal+bar
- Minimum gap between alerts (configurable)
- Re-alerts only if:
  - Direction flips
  - Price moves additional step % in same direction
  - Cooldown expired with increased severity

## Logging

Logs are written to both console and file (`stock_alerts.log`). Log levels:
- DEBUG: Detailed execution flow
- INFO: Normal operations
- WARNING: Recoverable issues
- ERROR: Errors requiring attention

## Troubleshooting

### Rate Limits
If you hit Twelve Data rate limits, the system will log warnings and retry with backoff.

### Missing Symbols
UK tickers must include `.L` suffix (e.g., `BARC.L`). Check logs for symbol validation errors.

### Email Not Sending
- Verify SMTP credentials
- For Gmail, use App Password (not regular password)
- Check firewall/network settings

## License

MIT
