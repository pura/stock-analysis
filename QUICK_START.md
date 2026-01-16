# Quick Start Guide

## Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

## Step 2: Get Your API Key

1. Sign up at [Twelve Data](https://twelvedata.com/pricing)
2. Get your free API key from the dashboard
3. Free tier includes 800 requests/day

## Step 3: Configure Email (Gmail Example)

### For Gmail:
1. Enable 2-Factor Authentication on your Google account
2. Go to [App Passwords](https://myaccount.google.com/apppasswords)
3. Generate an App Password for "Mail"
4. Use this App Password (not your regular password) in `.env`

### For Other Email Providers:
- **Outlook/Hotmail**: `smtp-mail.outlook.com`, port 587
- **Yahoo**: `smtp.mail.yahoo.com`, port 587
- **Custom SMTP**: Use your provider's SMTP settings

## Step 4: Create Configuration File

```bash
# Copy the example file
cp .env.example .env

# Edit with your values
nano .env  # or use your preferred editor
```

### Minimum Required Configuration:

```bash
# REQUIRED - Fill these in:
TWELVE_DATA_API_KEY=your_actual_api_key_here
WATCHLIST=AAPL,MSFT,GOOGL
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
ALERT_EMAIL_TO=where_to_send_alerts@example.com
```

### Example Complete Configuration:

```bash
TWELVE_DATA_API_KEY=abc123xyz789
WATCHLIST=AAPL,MSFT,GOOGL,BARC.L,TSCO.L
HISTORY_DAYS=365
MOVE_PCT=1.5
VOLUME_SPIKE_MULT=2.0
BREAKOUT_LOOKBACK=20
MIN_ALERT_GAP_MIN=60
RE_ALERT_STEP_PCT=0.5
MARKET_OPEN_HOUR=8
MARKET_CLOSE_HOUR=16
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=myemail@gmail.com
SMTP_PASSWORD=abcd efgh ijkl mnop
ALERT_EMAIL_TO=alerts@mycompany.com
SQLITE_PATH=database/stock_analysis.db
LOG_LEVEL=INFO
LOG_FILE=stock_alerts.log
```

## Step 5: Run Initial Backfill

Download 1 year of historical data for all symbols:

```bash
python -m agents.backfill_agent
```

**Expected output:**
```
INFO - Starting backfill for 3 symbols...
INFO - Backfilling 365 days of data for AAPL...
INFO - AAPL: Stored 252 daily OHLC records
INFO - Backfilling 365 days of data for MSFT...
INFO - MSFT: Stored 252 daily OHLC records
INFO - Backfill completed
```

**Note:** This may take a few minutes depending on your watchlist size and API rate limits.

## Step 6: Test Monitoring (Manual Run)

Run the monitoring cycle manually to test:

```bash
python main.py
```

**Expected output:**
```
INFO - ============================================================
INFO - Starting monitoring cycle
INFO - Watchlist: AAPL, MSFT, GOOGL
INFO - ============================================================
INFO - Monitoring AAPL...
INFO - AAPL: Detected 0 alertable signals
INFO - Monitoring MSFT...
INFO - MSFT: Detected 0 alertable signals
INFO - No alertable signals detected
```

If signals are detected, you'll see:
```
INFO - AAPL: Detected 1 alertable signals
INFO - Fetching news for 1 signals...
INFO - Generating alert summary...
INFO - Sending alert email...
INFO - Alert email sent successfully
```

## Step 7: Set Up Automated Monitoring

### Option A: Cron (Linux/macOS)

Edit your crontab:
```bash
crontab -e
```

Add these lines:

```bash
# Every 30 minutes during market hours (Mon-Fri, 8 AM - 4 PM)
*/30 8-16 * * 1-5 cd /path/to/Stock-Ayalyst && /usr/bin/python3 main.py >> /var/log/stock_alerts.log 2>&1

# Daily end-of-day job (5 PM, Mon-Fri)
0 17 * * 1-5 cd /path/to/Stock-Ayalyst && /usr/bin/python3 -m agents.eod_agent >> /var/log/stock_alerts_eod.log 2>&1
```

**Important:** Replace `/path/to/Stock-Ayalyst` with your actual project path.

### Option B: Systemd Timer (Linux)

Create `/etc/systemd/system/stock-alerts.service`:
```ini
[Unit]
Description=Stock Alert Monitoring
After=network.target

[Service]
Type=oneshot
User=your_username
WorkingDirectory=/path/to/Stock-Ayalyst
ExecStart=/usr/bin/python3 /path/to/Stock-Ayalyst/main.py
Environment="PATH=/usr/bin:/usr/local/bin"
```

Create `/etc/systemd/system/stock-alerts.timer`:
```ini
[Unit]
Description=Run Stock Alerts Every 30 Minutes
Requires=stock-alerts.service

[Timer]
OnCalendar=Mon-Fri 08:00/30:00
OnCalendar=Mon-Fri 16:00

[Install]
WantedBy=timers.target
```

Enable and start:
```bash
sudo systemctl enable stock-alerts.timer
sudo systemctl start stock-alerts.timer
```

### Option C: Manual/Scheduled Task (Windows)

Use Windows Task Scheduler to run:
```
python C:\path\to\Stock-Ayalyst\main.py
```

Schedule: Every 30 minutes, Mon-Fri, 8 AM - 4 PM

## Step 8: Verify It's Working

1. **Check logs:**
   ```bash
   tail -f stock_alerts.log
   ```

2. **Check database:**
   ```bash
   sqlite3 database/stock_analysis.db "SELECT COUNT(*) FROM stock_history;"
   ```

3. **Check for signals:**
   ```bash
   sqlite3 database/stock_analysis.db "SELECT symbol, signal_type, datetime FROM signals ORDER BY datetime DESC LIMIT 10;"
   ```

## Troubleshooting

### "TWELVE_DATA_API_KEY is required"
- Make sure `.env` file exists and contains `TWELVE_DATA_API_KEY=your_key`

### "Rate limit" errors
- Free tier has 800 requests/day limit
- System will retry with backoff automatically
- Consider reducing watchlist size or increasing intervals

### Email not sending
- **Gmail**: Make sure you're using App Password, not regular password
- Check SMTP credentials are correct
- Verify firewall isn't blocking port 587
- Check spam folder for test emails

### "Market is closed" message
- This is normal outside market hours
- System only runs during configured market hours
- Adjust `MARKET_OPEN_HOUR` and `MARKET_CLOSE_HOUR` if needed

### No signals detected
- This is normal - signals only trigger when thresholds are met
- Lower `MOVE_PCT` to 0.5% for more sensitive alerts (testing)
- Check logs to see if monitoring is running

### Database errors
- Make sure you have write permissions in the project directory
- Check `SQLITE_PATH` in `.env` is correct
- Delete `database/stock_analysis.db` and re-run backfill if corrupted

## Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TWELVE_DATA_API_KEY` | ✅ Yes | - | Your Twelve Data API key |
| `WATCHLIST` | ✅ Yes | - | Comma-separated stock symbols |
| `SMTP_USER` | ✅ Yes | - | Email address for sending |
| `SMTP_PASSWORD` | ✅ Yes | - | Email password/App Password |
| `ALERT_EMAIL_TO` | ✅ Yes | - | Where to send alerts |
| `HISTORY_DAYS` | No | 365 | Days of historical data |
| `MOVE_PCT` | No | 1.5 | % change threshold |
| `VOLUME_SPIKE_MULT` | No | 2.0 | Volume multiplier |
| `BREAKOUT_LOOKBACK` | No | 20 | Bars for breakout detection |
| `MIN_ALERT_GAP_MIN` | No | 60 | Minutes between alerts |
| `RE_ALERT_STEP_PCT` | No | 0.5 | % for re-alert |
| `MARKET_OPEN_HOUR` | No | 8 | Market open (24h) |
| `MARKET_CLOSE_HOUR` | No | 16 | Market close (24h) |
| `SQLITE_PATH` | No | database/stock_analysis.db | Main database (all tables) |
| `LOG_LEVEL` | No | INFO | Logging level |
| `LOG_FILE` | No | stock_alerts.log | Log file path |

## Next Steps

1. ✅ Backfill completed
2. ✅ Test run successful
3. ✅ Email alerts working
4. ✅ Set up cron/automation
5. ✅ Monitor logs regularly
6. ✅ Adjust thresholds as needed

## Support

- Check logs: `tail -f stock_alerts.log`
- Review database: `sqlite3 database/stock_analysis.db`
- Test email: Modify `main.py` temporarily to force an alert
- Adjust thresholds: Lower `MOVE_PCT` for more alerts, raise for fewer
