"""News collection agent: gathers financial news for tickers via web search."""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from ddgs import DDGS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logger = logging.getLogger("trade4me.research")


def search_ticker_news(ticker: str, company_name: str | None = None, max_results: int = 8) -> list[dict]:
    """Search DuckDuckGo News for recent articles about a ticker.

    Returns list of {title, body, url, date, source} dicts.
    """
    query = f"{ticker} stock"
    if company_name:
        query = f"{company_name} ({ticker}) stock news"

    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results, timelimit="w"))
        articles = []
        for r in results:
            articles.append({
                "title": r.get("title", ""),
                "body": r.get("body", ""),
                "url": r.get("url", ""),
                "date": r.get("date", ""),
                "source": r.get("source", ""),
            })
        logger.info(f"  {ticker}: found {len(articles)} news articles")
        return articles
    except Exception as e:
        logger.warning(f"  {ticker}: news search failed: {e}")
        return []


def get_company_names(tickers: list[str], universe_path: str | None = None) -> dict[str, str]:
    """Load ticker → company name mapping from universe CSV if available."""
    names: dict[str, str] = {}
    if universe_path:
        try:
            import pandas as pd
            df = pd.read_csv(universe_path)
            if "company_name" in df.columns:
                for _, row in df.iterrows():
                    names[row["ticker"]] = row["company_name"]
        except Exception:
            pass
    return names


def collect_news_batch(
    tickers: list[str],
    max_per_ticker: int = 8,
    universe_path: str | None = None,
) -> dict[str, list[dict]]:
    """Collect news for a batch of tickers.

    Returns {ticker: [articles]} dict.
    """
    names = get_company_names(tickers, universe_path)
    results: dict[str, list[dict]] = {}

    for ticker in tickers:
        articles = search_ticker_news(
            ticker,
            company_name=names.get(ticker),
            max_results=max_per_ticker,
        )
        results[ticker] = articles

    return results
