"""News collection agent: gathers financial news for tickers via web search.

Only articles from trusted financial sources are kept — see TRUSTED_SOURCES.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from ddgs import DDGS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logger = logging.getLogger("trade4me.research")

# Trusted financial news sources.  DuckDuckGo returns a short "source" string
# (e.g. "Reuters", "Yahoo Finance").  We lowercase-match against these tokens
# so "The Wall Street Journal" matches "wall street journal".
#
# Tier 1 — Wire services & official filings
# Tier 2 — Major financial media
# Tier 3 — Reputable general/tech/business media
TRUSTED_SOURCES: set[str] = {
    # Tier 1: wire services, exchanges, regulators
    "reuters", "associated press", "ap news",
    "bloomberg", "sec.gov", "edgar",
    "dow jones", "pr newswire", "business wire", "globenewswire",

    # Tier 2: dedicated financial media
    "cnbc", "yahoo finance", "marketwatch", "barrons", "barron's",
    "wall street journal", "wsj", "financial times", "ft.com",
    "investor's business daily", "ibd", "thestreet",
    "seeking alpha", "motley fool", "benzinga", "zacks",
    "morningstar", "tipranks", "stockanalysis",
    "investopedia", "kiplinger",

    # Tier 3: major business & tech media
    "fortune", "forbes", "business insider", "insider",
    "new york times", "nytimes", "washington post",
    "cnn", "cnn business", "bbc", "bbc news",
    "techcrunch", "the verge", "ars technica", "wired",
    "the economist", "nikkei", "south china morning post",
    "the guardian", "usa today", "los angeles times",

    # Tier 3: sector-specific
    "fierce pharma", "endpoints news", "stat news",
    "the information", "semafor", "axios",
    "electrek", "cleantechnica",
}


def _is_trusted_source(source: str) -> bool:
    """Check if a source name matches our whitelist (case-insensitive substring)."""
    lower = source.lower().strip()
    if not lower:
        return False
    for trusted in TRUSTED_SOURCES:
        if trusted in lower or lower in trusted:
            return True
    return False


def search_ticker_news(ticker: str, company_name: str | None = None, max_results: int = 8) -> list[dict]:
    """Search DuckDuckGo News for recent articles about a ticker.

    Returns list of {title, body, url, date, source} dicts.
    Only articles from trusted sources are included.
    """
    query = f"{ticker} stock"
    if company_name:
        query = f"{company_name} ({ticker}) stock news"

    try:
        # Fetch extra results to compensate for filtering
        fetch_count = max_results * 3
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=fetch_count, timelimit="w"))

        articles = []
        skipped = []
        for r in results:
            source = r.get("source", "")
            if _is_trusted_source(source):
                articles.append({
                    "title": r.get("title", ""),
                    "body": r.get("body", ""),
                    "url": r.get("url", ""),
                    "date": r.get("date", ""),
                    "source": source,
                })
            else:
                skipped.append(source)

        articles = articles[:max_results]

        if skipped:
            unique_skipped = sorted(set(skipped))
            logger.info(f"  {ticker}: kept {len(articles)} trusted, filtered {len(skipped)} untrusted ({', '.join(unique_skipped[:5])})")
        else:
            logger.info(f"  {ticker}: found {len(articles)} news articles (all trusted)")
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
    """Collect news for a batch of tickers in parallel.

    Returns {ticker: [articles]} dict.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    names = get_company_names(tickers, universe_path)
    results: dict[str, list[dict]] = {}

    def _fetch(ticker: str) -> tuple[str, list[dict]]:
        articles = search_ticker_news(
            ticker,
            company_name=names.get(ticker),
            max_results=max_per_ticker,
        )
        return ticker, articles

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, articles = future.result()
            results[ticker] = articles

    return results
