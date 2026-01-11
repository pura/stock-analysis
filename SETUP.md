# Setup Guide

## Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create `.env` file:**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and configuration
   ```

3. **Run initial backfill:**
   ```bash
   python -m agents.backfill_agent
   ```

4. **Test monitoring:**
   ```bash
   python main.py
   ```

## Environment Variables

Required variables in `.env`:

```bash
# Twelve Data API (required)
TWELVE_DATA_API_KEY=your_key_here

# Watchlist (required, comma-separated)
WATCHLIST=AAPL,MSFT,GOOGL,BARC.L

# Email Configuration (required for alerts)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
ALERT_EMAIL_TO=alerts@example.com

# Optional Configuration
HISTORY_DAYS=365
MOVE_PCT=1.5
VOLUME_SPIKE_MULT=2.0
BREAKOUT_LOOKBACK=20
MIN_ALERT_GAP_MIN=60
RE_ALERT_STEP_PCT=0.5
MARKET_OPEN_HOUR=8
MARKET_CLOSE_HOUR=16
SQLITE_PATH=database/stock_alerts.db
LOG_LEVEL=INFO
LOG_FILE=stock_alerts.log
```

## Gmail Setup

For Gmail SMTP:
1. Enable 2-factor authentication
2. Generate an App Password: https://myaccount.google.com/apppasswords
3. Use the App Password (not your regular password) in `SMTP_PASSWORD`

## Cron Setup

### Every 30 minutes during market hours:
```bash
*/30 8-16 * * 1-5 cd /path/to/Stock-Ayalyst && /usr/bin/python3 main.py >> /var/log/stock_alerts.log 2>&1
```

### Daily end-of-day (after market close):
```bash
0 17 * * 1-5 cd /path/to/Stock-Ayalyst && /usr/bin/python3 -m agents.eod_agent >> /var/log/stock_alerts_eod.log 2>&1
```

## File Structure

```
Stock-Ayalyst/
├── agents/              # Agent modules
│   ├── backfill_agent.py
│   ├── monitor_agent.py
│   ├── news_agent.py
│   ├── summarizer_agent.py
│   └── eod_agent.py
├── core/                # Core functionality
│   ├── config.py
│   ├── database.py
│   ├── signals.py
│   ├── email.py
│   └── tools.py
├── utils/               # Utilities
│   ├── market_hours.py
│   └── logging_config.py
├── database/            # Database files
│   ├── stock_alerts.db  # Main database
│   └── state.sqlite     # CrewAI state (auto-created)
├── data/                # Data files
│   └── sector_map.json
├── main.py              # Main entry point
└── requirements.txt
```

## Troubleshooting

### Rate Limits
If you hit Twelve Data rate limits, the system will automatically retry with backoff.

### Missing Symbols
- US tickers: Use standard format (AAPL, MSFT)
- UK tickers: Must include `.L` suffix (BARC.L, TSCO.L)

### Email Not Sending
- Verify SMTP credentials
- Check firewall settings
- For Gmail, ensure App Password is used

### Database Issues
- Database is created automatically on first run
- Location: `database/stock_alerts.db` (or configured path)
- All database files stored in `database/` folder
- WAL mode enabled for better concurrency
