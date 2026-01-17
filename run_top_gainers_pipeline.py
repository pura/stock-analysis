#!/usr/bin/env python3
"""
Top Gainers Pipeline Runner

Runs the complete top gainers pipeline:
1. Scrape top gainers from Yahoo Finance
2. Analyze trends using Twelve Data
3. Generate trade signals

Run this script every 30 minutes during market hours.
"""

import sys
import subprocess
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from utils.logging_config import setup_logging
from utils.market_hours import is_market_open
from core.config import Config

logger = logging.getLogger(__name__)


def run_agent(agent_module: str, agent_name: str) -> bool:
    """Run an agent module and return True if successful."""
    try:
        logger.info(f"Starting {agent_name}...")
        result = subprocess.run(
            [sys.executable, "-m", agent_module],
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout per agent
        )
        
        if result.returncode == 0:
            logger.info(f"✅ {agent_name} completed successfully")
            if result.stdout:
                logger.debug(f"{agent_name} output:\n{result.stdout}")
            return True
        else:
            logger.error(f"❌ {agent_name} failed with exit code {result.returncode}")
            if result.stderr:
                logger.error(f"{agent_name} error:\n{result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"❌ {agent_name} timed out after 10 minutes")
        return False
    except Exception as e:
        logger.error(f"❌ Error running {agent_name}: {e}", exc_info=True)
        return False


def main():
    """Run the complete top gainers pipeline."""
    setup_logging("INFO", "top_gainers_pipeline.log")
    
    logger.info("="*60)
    logger.info("Top Gainers Pipeline - Starting")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info("="*60)
    
    try:
        cfg = Config.from_env()
        
        # Check if market is open (optional - you can remove this if you want to run 24/7)
        if not is_market_open(cfg.market_open_hour, cfg.market_close_hour):
            logger.info("Market is closed, but continuing with pipeline...")
        
        # Step 1: Scrape top gainers
        logger.info("\n" + "="*60)
        logger.info("STEP 1: Scraping Top Gainers")
        logger.info("="*60)
        success1 = run_agent("agents.top_gainers.top_gainers_scrape_agent", "Top Gainers Scrape Agent")
        
        if not success1:
            logger.warning("Scrape agent failed, but continuing with pipeline...")
        
        # Step 2: Analyze trends
        logger.info("\n" + "="*60)
        logger.info("STEP 2: Analyzing Trends")
        logger.info("="*60)
        success2 = run_agent("agents.top_gainers.top_gainers_trend_agent", "Top Gainers Trend Agent")
        
        if not success2:
            logger.warning("Trend agent failed, but continuing with pipeline...")
        
        # Step 3: Generate trade signals
        logger.info("\n" + "="*60)
        logger.info("STEP 3: Generating Trade Signals")
        logger.info("="*60)
        success3 = run_agent("agents.top_gainers.top_gainers_trade_agent", "Top Gainers Trade Agent")
        
        # Summary
        logger.info("\n" + "="*60)
        logger.info("Pipeline Summary:")
        logger.info(f"  Scrape Agent: {'✅ Success' if success1 else '❌ Failed'}")
        logger.info(f"  Trend Agent: {'✅ Success' if success2 else '❌ Failed'}")
        logger.info(f"  Trade Agent: {'✅ Success' if success3 else '❌ Failed'}")
        logger.info("="*60)
        
        if success1 and success2 and success3:
            logger.info("✅ Pipeline completed successfully")
            return 0
        else:
            logger.warning("⚠️  Pipeline completed with some failures")
            return 1
            
    except Exception as e:
        logger.error(f"Fatal error in pipeline: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
