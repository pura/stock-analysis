"""Main entry point for stock alert system."""
import sys
import logging
from pathlib import Path

from core.config import Config
from core.database import connect, get_signals_with_news
from core.email import send_alert_email
from agents.monitor_agent import monitor_symbol
from agents.news_agent import fetch_news_for_signals
from agents.summarizer_agent import generate_alert_summary
from utils.market_hours import is_market_open
from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main():
    """Main monitoring cycle."""
    setup_logging("INFO", "stock_alerts.log")
    
    try:
        cfg = Config.from_env()
        
        if not cfg.twelve_data_api_key:
            raise ValueError("TWELVE_DATA_API_KEY is required")
        
        # Check if market is open
        if not is_market_open(cfg.market_open_hour, cfg.market_close_hour):
            logger.info("Market is closed, skipping monitoring cycle")
            return
        
        logger.info("="*60)
        logger.info("Starting monitoring cycle")
        logger.info(f"Watchlist: {', '.join(cfg.watchlist)}")
        logger.info("="*60)
        
        # Step 1: Monitor all symbols and detect signals
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
                logger.info(f"{symbol}: Detected {len(signals)} alertable signals")
            except Exception as e:
                logger.error(f"Error monitoring {symbol}: {e}", exc_info=True)
        
        if not all_signals:
            logger.info("No alertable signals detected")
            return
        
        logger.info(f"Total alertable signals: {len(all_signals)}")
        
        # Step 2: Fetch news for triggered tickers
        news_by_symbol = fetch_news_for_signals(all_signals, cfg, cfg.sqlite_path)
        
        # Step 3: Build signals with news data
        signals_with_news = []
        for sig in all_signals:
            # Get news for this signal
            signal_data = {
                "id": sig["signal_id"],
                "symbol": sig["symbol"],
                "signal_type": sig["signal"]["signal_type"],
                "metrics": sig["signal"]["metrics"],
                "severity": sig["signal"]["severity"],
                "news": news_by_symbol.get(sig["symbol"], {}).get("direct", [])[:3]
            }
            signals_with_news.append(signal_data)
        
        # Step 4: Generate alert summary using CrewAI
        logger.info("Generating alert summary...")
        alert_message = generate_alert_summary(signals_with_news, cfg)
        
        if not alert_message:
            logger.warning("Empty alert message generated")
            return
        
        # Step 5: Send email alert
        logger.info("Sending alert email...")
        success = send_alert_email(
            cfg.smtp_host,
            cfg.smtp_port,
            cfg.smtp_user,
            cfg.smtp_password,
            cfg.alert_email_to,
            "Stock Alert: Price Movements Detected",
            alert_message
        )
        
        if success:
            logger.info("Alert email sent successfully")
            print("\n" + "="*60)
            print("ALERT SENT")
            print("="*60)
            print(alert_message)
            print("="*60 + "\n")
        else:
            logger.error("Failed to send alert email")
            # Still print to console
            print("\n" + "="*60)
            print("ALERT (Email Failed)")
            print("="*60)
            print(alert_message)
            print("="*60 + "\n")
        
        logger.info("Monitoring cycle completed")
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
