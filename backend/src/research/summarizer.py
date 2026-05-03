"""AI-powered news summarization using Claude."""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.research.schema import NewsResearch, BinaryEvent

logger = logging.getLogger("trademark.research")

SUMMARIZER_SYSTEM = """You are a financial news research assistant. Given news headlines and snippets about a stock, produce a structured research summary.

Your job:
1. Summarize key developments in 2-3 sentences
2. Identify upcoming binary events (earnings, regulatory decisions, product launches)
3. Flag risk factors a quantitative model would NOT capture
4. Identify positive catalysts/opportunities
5. Assess overall news sentiment

You must NOT:
- Make price predictions or recommend buy/sell
- Hallucinate events not mentioned in the provided headlines
- Provide analysis beyond what the news supports

Return ONLY valid JSON (no markdown fences) matching this schema:
{
  "ai_summary": "<2-3 sentence summary>",
  "sentiment": "positive" | "negative" | "neutral" | "mixed",
  "binary_events": [
    {
      "event_type": "earnings" | "regulatory" | "product_launch" | "legal" | "management",
      "expected_date": "<ISO date or null>",
      "description": "<brief description>",
      "potential_impact": "high" | "medium" | "low"
    }
  ],
  "risk_factors": ["<risk 1>", ...],
  "opportunities": ["<opportunity 1>", ...],
  "confidence": <0.0-1.0, based on how much relevant news was found>
}

If no meaningful news is found, return neutral sentiment with confidence 0.1 and empty lists."""


def summarize_ticker_news(ticker: str, articles: list[dict]) -> NewsResearch:
    """Send articles to Claude for structured summarization.

    Returns a NewsResearch object.
    """
    today = datetime.now().strftime("%Y-%m-%d")

    if not articles:
        return NewsResearch(
            ticker=ticker,
            research_date=today,
            ai_summary="No recent news found.",
            sentiment="neutral",
            confidence=0.0,
            data_sources=[],
        )

    # Build context from articles
    headlines = [a["title"] for a in articles if a.get("title")]
    snippets = []
    for a in articles:
        snippet = f"[{a.get('source', 'Unknown')}] {a.get('title', '')}"
        if a.get("body"):
            snippet += f"\n  {a['body'][:300]}"
        snippets.append(snippet)

    sources = list(set(a.get("source", "Unknown") for a in articles))

    user_prompt = f"""Ticker: {ticker}
Date: {today}
Number of articles: {len(articles)}

Recent news:
{chr(10).join(snippets)}"""

    try:
        client = anthropic.Anthropic(api_key=settings.api_keys.anthropic_api_key)
        response = client.messages.create(
            model=settings.judge.model,
            max_tokens=1024,
            temperature=0.0,
            system=SUMMARIZER_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw_text = response.content[0].text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(raw_text)

        binary_events = [
            BinaryEvent(**e) for e in data.get("binary_events", [])
        ]

        return NewsResearch(
            ticker=ticker,
            research_date=today,
            headlines=headlines,
            ai_summary=data.get("ai_summary", ""),
            sentiment=data.get("sentiment", "neutral"),
            binary_events=binary_events,
            risk_factors=data.get("risk_factors", []),
            opportunities=data.get("opportunities", []),
            data_sources=sources,
            confidence=data.get("confidence", 0.5),
        )

    except Exception as e:
        logger.error(f"  {ticker}: AI summarization failed: {e}")
        return NewsResearch(
            ticker=ticker,
            research_date=today,
            headlines=headlines,
            ai_summary=f"Summarization failed: {e}",
            sentiment="neutral",
            confidence=0.0,
            data_sources=sources,
        )


def research_tickers(
    tickers: list[str],
    news_by_ticker: dict[str, list[dict]],
) -> list[NewsResearch]:
    """Run AI summarization for a batch of tickers in parallel.

    Returns list of NewsResearch objects.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _summarize(ticker: str) -> NewsResearch:
        articles = news_by_ticker.get(ticker, [])
        logger.info(f"  Summarizing {ticker} ({len(articles)} articles)...")
        research = summarize_ticker_news(ticker, articles)
        logger.info(f"    {ticker}: sentiment={research.sentiment}, confidence={research.confidence:.0%}")
        return research

    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_summarize, t): t for t in tickers}
        for future in as_completed(futures):
            results.append(future.result())

    return results


def store_research(research_list: list[NewsResearch]) -> None:
    """Store research results to DuckDB."""
    from src.db.schema import get_connection

    if not research_list:
        return

    con = get_connection()
    for r in research_list:
        con.execute("""
            DELETE FROM news_research WHERE ticker = ? AND research_date = ?
        """, [r.ticker, r.research_date])

        con.execute("""
            INSERT INTO news_research
            (ticker, research_date, headlines, ai_summary, sentiment,
             binary_events, risk_factors, opportunities, data_sources, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            r.ticker,
            r.research_date,
            json.dumps(r.headlines),
            r.ai_summary,
            r.sentiment,
            json.dumps([e.model_dump() for e in r.binary_events]),
            json.dumps(r.risk_factors),
            json.dumps(r.opportunities),
            json.dumps(r.data_sources),
            r.confidence,
        ])

    con.close()
    logger.info(f"  Stored research for {len(research_list)} tickers")
