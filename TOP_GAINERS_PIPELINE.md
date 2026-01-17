# Top Gainers Pipeline Setup

This guide shows how to run the top gainers pipeline every 30 minutes on your local machine.

## Pipeline Overview

The pipeline runs three agents in sequence:
1. **top_gainers_scrape_agent** - Scrapes top 25 gainers from Yahoo Finance
2. **top_gainers_trend_agent** - Analyzes price trends over last 2 hours
3. **top_gainers_trade_agent** - Generates buy/sell signals based on trends

## Quick Start

### Option 1: Run Manually

```bash
cd /Users/puraskarsapkota/Projects/Stock-Ayalyst
python3 runner/run_top_gainers_pipeline.py
```

Or run individual agents:
```bash
# Scrape agent
python3 -m agents.top_gainers.top_gainers_scrape_agent

# Trend agent
python3 -m agents.top_gainers.top_gainers_trend_agent

# Trade agent
python3 -m agents.top_gainers.top_gainers_trade_agent
```

### Option 2: Set Up Cron Job (macOS/Linux)

1. **Open your crontab:**
   ```bash
   crontab -e
   ```

2. **Add this line** (adjust the path to your project):
   ```bash
   */30 8-16 * * 1-5 cd /Users/puraskarsapkota/Projects/Stock-Ayalyst && /usr/bin/python3 runner/run_top_gainers_pipeline.py >> ~/top_gainers_pipeline.log 2>&1
   ```
   
   Or run individual agents:
   ```bash
   */30 8-16 * * 1-5 cd /Users/puraskarsapkota/Projects/Stock-Ayalyst && /usr/bin/python3 -m agents.top_gainers.top_gainers_scrape_agent >> ~/top_gainers_scrape.log 2>&1
   */30 8-16 * * 1-5 cd /Users/puraskarsapkota/Projects/Stock-Ayalyst && /usr/bin/python3 -m agents.top_gainers.top_gainers_trend_agent >> ~/top_gainers_trend.log 2>&1
   */30 8-16 * * 1-5 cd /Users/puraskarsapkota/Projects/Stock-Ayalyst && /usr/bin/python3 -m agents.top_gainers.top_gainers_trade_agent >> ~/top_gainers_trade.log 2>&1
   ```

   This runs every 30 minutes between 8 AM and 4 PM, Monday through Friday.

3. **Find your Python path** (if needed):
   ```bash
   which python3
   ```

4. **Verify cron is running:**
   ```bash
   crontab -l
   ```

### Option 3: Use launchd (macOS - Recommended)

macOS has a better scheduler called `launchd`. Create a plist file:

1. **Create the plist file:**
   ```bash
   nano ~/Library/LaunchAgents/com.stockanalyst.topgainers.plist
   ```

2. **Add this content** (adjust paths as needed):
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
       <key>Label</key>
       <string>com.stockanalyst.topgainers</string>
       <key>ProgramArguments</key>
       <array>
           <string>/usr/bin/python3</string>
           <string>/Users/puraskarsapkota/Projects/Stock-Ayalyst/runner/run_top_gainers_pipeline.py</string>
       </array>
       <key>EnvironmentVariables</key>
       <dict>
           <key>PATH</key>
           <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
       </dict>
       <key>WorkingDirectory</key>
       <string>/Users/puraskarsapkota/Projects/Stock-Ayalyst</string>
       <key>StartInterval</key>
       <integer>1800</integer>
       <key>StandardOutPath</key>
       <string>/Users/puraskarsapkota/Projects/Stock-Ayalyst/top_gainers_pipeline.log</string>
       <key>StandardErrorPath</key>
       <string>/Users/puraskarsapkota/Projects/Stock-Ayalyst/top_gainers_pipeline_error.log</string>
       <key>RunAtLoad</key>
       <false/>
   </dict>
   </plist>
   ```

3. **Load the service:**
   ```bash
   launchctl load ~/Library/LaunchAgents/com.stockanalyst.topgainers.plist
   ```

4. **Start the service:**
   ```bash
   launchctl start com.stockanalyst.topgainers
   ```

5. **Check status:**
   ```bash
   launchctl list | grep stockanalyst
   ```

6. **To stop:**
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.stockanalyst.topgainers.plist
   ```

### Option 4: Python Scheduler (Simple Background Script)

Create a simple Python script that runs in the background:

```python
#!/usr/bin/env python3
import time
import subprocess
import sys
from datetime import datetime

while True:
    print(f"[{datetime.now()}] Running pipeline...")
    subprocess.run([sys.executable, "runner/run_top_gainers_pipeline.py"])
    print(f"[{datetime.now()}] Waiting 30 minutes...")
    time.sleep(1800)  # 30 minutes = 1800 seconds
```

Run it in the background:
```bash
nohup python3 scheduler.py > scheduler.log 2>&1 &
```

## Logs

- Pipeline logs: `top_gainers_pipeline.log`
- Individual agent logs:
  - `top_gainers_scrape.log` (from scrape agent)
  - `top_gainers_trend_twelvedata.log` (from trend agent)
  - `top_gainers_trade.log` (from trade agent)

## Troubleshooting

1. **Check if Python path is correct:**
   ```bash
   which python3
   ```

2. **Test the pipeline manually first:**
   ```bash
   python3 runner/run_top_gainers_pipeline.py
   ```

3. **Check cron logs** (macOS):
   ```bash
   grep CRON /var/log/system.log
   ```

4. **Verify environment variables are set:**
   ```bash
   source .env  # or export them in your shell
   ```

## Schedule Times

- **Market Hours**: 8:00 AM - 4:00 PM ET (Monday-Friday)
- **Run Frequency**: Every 30 minutes
- **Cron Expression**: `*/30 8-16 * * 1-5`

Adjust times based on your timezone and market hours.
