"""CrewAI agent for summarizing alerts."""
import sys
import logging
import os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from crewai import Agent, Task, Crew
from core.config import Config
# Summarizer doesn't need database access - works with provided signals
from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


def generate_alert_summary(signals: list[dict], cfg: Config) -> str:
    """Generate alert summary using CrewAI."""
    if not signals:
        return ""
    
    # Group signals by symbol
    signals_by_symbol = {}
    for sig in signals:
        symbol = sig["symbol"]
        if symbol not in signals_by_symbol:
            signals_by_symbol[symbol] = []
        signals_by_symbol[symbol].append(sig)
    
    # Build context
    context_lines = ["STOCK ALERT SUMMARY\n" + "="*60 + "\n"]
    context_lines.append(f"Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n")
    
    for symbol, symbol_signals in signals_by_symbol.items():
        context_lines.append(f"\n{symbol}:")
        for sig in symbol_signals:
            signal_type = sig["signal_type"]
            metrics = sig["metrics"]
            severity = sig["severity"]
            
            if signal_type == "move_from_open":
                pct = metrics.get("pct_change", 0)
                direction = "UP" if pct > 0 else "DOWN"
                context_lines.append(f"  - {signal_type.upper()}: {abs(pct):.2f}% {direction} from open")
            elif signal_type == "volume_spike":
                mult = metrics.get("multiplier", 0)
                context_lines.append(f"  - {signal_type.upper()}: {mult:.1f}x average volume")
            elif signal_type in ["breakout", "breakdown"]:
                context_lines.append(f"  - {signal_type.upper()}: Price {signal_type}")
            
            # Add news
            news = sig.get("news", [])
            if news:
                context_lines.append("    News:")
                for item in news[:3]:
                    relevance = item.get("relevance", "unknown")
                    if relevance != "none_found":
                        context_lines.append(f"      • {item.get('title', '')[:80]}")
                        context_lines.append(f"        {item.get('url', '')}")
            else:
                context_lines.append("    News: No clear driver found")
    
    context = "\n".join(context_lines)
    
    # Create CrewAI agent
    summarizer = Agent(
        role="Stock Alert Summarizer",
        goal="Create concise, factual stock alert summaries with relevant news context",
        backstory="""You are a professional financial alert writer. You create clear, 
        no-hype summaries of stock price movements with relevant news context. You 
        explicitly state when no clear driver is found. You group alerts by ticker 
        and keep messages under 2000 characters.""",
        verbose=False,
    )
    
    task = Task(
        description=(
            "Given stock signals and news context, create a clean alert message:\n"
            "- Group by ticker\n"
            "- List each signal type and key metrics\n"
            "- Include 1-3 most relevant headlines per ticker with timestamps\n"
            "- Explicitly say 'No clear driver found' when no relevant news\n"
            "- Keep it concise, factual, no hype\n"
            "- Format: Ticker, signals, news (if any), timestamp\n\n"
            f"Context:\n{context}"
        ),
        expected_output="A single formatted alert message ready for email delivery",
        agent=summarizer,
    )
    
    # Configure CrewAI to use database folder for state.sqlite
    database_dir = Path("database")
    database_dir.mkdir(exist_ok=True)
    original_cwd = os.getcwd()
    
    try:
        # Change to database directory so CrewAI creates state.sqlite there
        os.chdir(database_dir)
        crew = Crew(agents=[summarizer], tasks=[task], verbose=False)
        result = crew.kickoff()
        return str(result).strip()
    except Exception as e:
        logger.error(f"Error generating summary: {e}", exc_info=True)
        # Fallback to simple format
        return context
    finally:
        # Restore original working directory
        os.chdir(original_cwd)


if __name__ == "__main__":
    setup_logging("INFO", "summarizer.log")
    # Typically called from main.py
