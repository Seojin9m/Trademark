"""LangChain tools for the chatbot agent.

Each tool calls internal Python functions directly — NOT HTTP endpoints.
This avoids network overhead and gives the agent structured data.
"""

import json
import sys
from pathlib import Path

from langchain_core.tools import tool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import settings
from src.db.schema import get_connection


# ─── Helper ──────────────────────────────────────────────────────────────────

def _safe_json(obj: object) -> str:
    """Serialize to JSON, handling NaN / Timestamp etc."""
    import pandas as pd

    def default(o):
        if isinstance(o, (pd.Timestamp,)):
            return o.isoformat()
        if isinstance(o, float) and (o != o):  # NaN
            return None
        raise TypeError(f"Not serializable: {type(o)}")

    return json.dumps(obj, default=default)


# ─── 1. Portfolio ────────────────────────────────────────────────────────────

@tool
def get_portfolio_summary() -> str:
    """Get the current portfolio: positions, cash, total value, unrealized P&L, and weight per holding."""
    from src.signals.portfolio_engine import (
        load_portfolio_state,
        compute_portfolio_weights,
    )
    from src.simulation.pnl import compute_pnl
    from src.api.main import get_live_prices

    portfolio = load_portfolio_state()
    tickers = [p["ticker"] for p in portfolio["positions"]]
    prices = get_live_prices(tickers, portfolio)
    pnl = compute_pnl(portfolio, prices)
    weights = compute_portfolio_weights(portfolio, prices)

    summary = {
        "total_value": pnl["total_portfolio_value"],
        "cash": pnl["cash"],
        "total_unrealized_pnl": pnl["total_unrealized_pnl"],
        "total_return_pct": pnl["total_return_pct"],
        "n_positions": len(pnl["positions"]),
        "positions": [
            {
                "ticker": p["ticker"],
                "shares": p["shares"],
                "cost_basis": p["cost_basis"],
                "current_price": p["current_price"],
                "market_value": p["market_value"],
                "unrealized_pnl": p["unrealized_pnl"],
                "unrealized_pct": p["unrealized_pct"],
                "weight": round(weights.get(p["ticker"], 0), 4),
            }
            for p in pnl["positions"]
        ],
    }
    return _safe_json(summary)


# ─── 2. Factor Scores ───────────────────────────────────────────────────────

@tool
def get_factor_scores(ticker: str = "") -> str:
    """Get latest factor scores (composite, decile, momentum, EPS growth, etc.).
    Optionally filter by ticker. Returns all tickers if ticker is empty."""
    con = get_connection()
    if ticker:
        df = con.execute("""
            SELECT * FROM factor_scores
            WHERE ticker = ? AND date = (SELECT MAX(date) FROM factor_scores)
        """, [ticker.upper()]).fetchdf()
    else:
        df = con.execute("""
            SELECT * FROM factor_scores
            WHERE date = (SELECT MAX(date) FROM factor_scores)
            ORDER BY composite_score DESC
            LIMIT 50
        """).fetchdf()
    con.close()
    if df.empty:
        return json.dumps({"message": "No factor scores found"})
    return df.to_json(orient="records", date_format="iso")


# ─── 3. Trade Proposals ─────────────────────────────────────────────────────

@tool
def get_trade_proposals(status: str = "", limit: int = 30) -> str:
    """Get trade proposals. Optionally filter by status (PENDING, APPROVED, REJECTED, EXECUTED, NEEDS_REVIEW, NO_ACTION).
    Returns recent proposals with signal data and judge response."""
    con = get_connection()
    if status:
        df = con.execute("""
            SELECT * FROM trade_proposals
            WHERE status = ?
            ORDER BY created_at DESC LIMIT ?
        """, [status.upper(), limit]).fetchdf()
    else:
        df = con.execute("""
            SELECT * FROM trade_proposals
            ORDER BY created_at DESC LIMIT ?
        """, [limit]).fetchdf()
    con.close()
    if df.empty:
        return json.dumps({"message": "No proposals found", "count": 0})
    records = json.loads(df.to_json(orient="records", date_format="iso"))
    return json.dumps({"count": len(records), "proposals": records})


# ─── 4. Single Proposal Detail ──────────────────────────────────────────────

@tool
def get_proposal_detail(proposal_id: str) -> str:
    """Get full details of a specific trade proposal including signal data, constraint check, and judge response."""
    con = get_connection()
    df = con.execute(
        "SELECT * FROM trade_proposals WHERE proposal_id = ?", [proposal_id]
    ).fetchdf()
    con.close()
    if df.empty:
        return json.dumps({"error": f"Proposal {proposal_id} not found"})
    record = json.loads(df.to_json(orient="records", date_format="iso"))[0]
    # Parse JSON fields for better readability
    for field in ("signal_data", "constraint_check", "judge_response"):
        val = record.get(field)
        if isinstance(val, str):
            try:
                record[field] = json.loads(val)
            except Exception:
                pass
    return json.dumps(record)


# ─── 5. Trade Executions ────────────────────────────────────────────────────

@tool
def get_trade_executions(ticker: str = "", limit: int = 30) -> str:
    """Get actual executed trades (the trades that were applied to the portfolio).
    Optionally filter by ticker."""
    con = get_connection()
    if ticker:
        df = con.execute("""
            SELECT * FROM trade_executions
            WHERE ticker = ?
            ORDER BY executed_at DESC LIMIT ?
        """, [ticker.upper(), limit]).fetchdf()
    else:
        df = con.execute("""
            SELECT * FROM trade_executions
            ORDER BY executed_at DESC LIMIT ?
        """, [limit]).fetchdf()
    con.close()
    if df.empty:
        return json.dumps({"message": "No executions found", "count": 0})
    records = json.loads(df.to_json(orient="records", date_format="iso"))
    return json.dumps({"count": len(records), "executions": records})


# ─── 6. Judge Log ───────────────────────────────────────────────────────────

@tool
def get_judge_decisions(limit: int = 20) -> str:
    """Get recent LLM judge decisions: verdict, confidence, model used, and reasoning."""
    from src.judge.client import get_judge_log
    logs = get_judge_log(limit)
    return json.dumps({"count": len(logs), "decisions": logs})


# ─── 7. Risk Metrics ────────────────────────────────────────────────────────

@tool
def get_risk_metrics() -> str:
    """Get current risk metrics: portfolio value, return, cash %, sector concentration, drawdown levels."""
    import pandas as pd
    from src.signals.portfolio_engine import (
        load_portfolio_state,
        get_current_prices,
        compute_portfolio_weights,
    )
    from src.simulation.pnl import compute_pnl

    portfolio = load_portfolio_state()
    tickers = [p["ticker"] for p in portfolio["positions"]]
    prices = get_current_prices(tickers)
    weights = compute_portfolio_weights(portfolio, prices)
    pnl = compute_pnl(portfolio, prices)

    universe = pd.read_csv(settings.paths.universe_path)
    sector_weights = {}
    for ticker, weight in weights.items():
        sector = universe.loc[universe["ticker"] == ticker, "sub_sector"]
        if not sector.empty:
            s = sector.iloc[0]
            sector_weights[s] = round(sector_weights.get(s, 0) + weight, 4)

    return json.dumps({
        "portfolio_value": pnl["total_portfolio_value"],
        "total_return_pct": pnl["total_return_pct"],
        "unrealized_pnl": pnl["total_unrealized_pnl"],
        "cash_pct": round(pnl["cash"] / pnl["total_portfolio_value"], 4) if pnl["total_portfolio_value"] > 0 else 0,
        "n_positions": len(portfolio["positions"]),
        "sector_weights": sector_weights,
        "drawdown_alert_level": settings.strategy.max_portfolio_drawdown_alert,
        "drawdown_halt_level": settings.strategy.max_portfolio_drawdown_halt,
    })


# ─── 8. News Research ───────────────────────────────────────────────────────

@tool
def get_news_research(ticker: str = "", limit: int = 10) -> str:
    """Get recent AI-generated news research: headlines, sentiment, binary events, risk factors, opportunities.
    Optionally filter by ticker."""
    con = get_connection()
    if ticker:
        df = con.execute("""
            SELECT * FROM news_research
            WHERE ticker = ?
            ORDER BY research_date DESC LIMIT ?
        """, [ticker.upper(), limit]).fetchdf()
    else:
        df = con.execute("""
            SELECT * FROM news_research
            WHERE research_date = (SELECT MAX(research_date) FROM news_research)
            ORDER BY confidence DESC LIMIT ?
        """, [limit]).fetchdf()
    con.close()
    if df.empty:
        return json.dumps({"message": "No research data found"})
    records = json.loads(df.to_json(orient="records", date_format="iso"))
    return json.dumps({"count": len(records), "research": records})


# ─── 9. Universe ─────────────────────────────────────────────────────────────

@tool
def get_stock_universe() -> str:
    """Get the investable stock universe with sector and sub-sector tags."""
    import pandas as pd
    df = pd.read_csv(settings.paths.universe_path)
    return df.to_json(orient="records")


# ─── 10. Learning Outcomes ───────────────────────────────────────────────────

@tool
def get_learning_data() -> str:
    """Get self-learning data: decision outcome summary (win rate, avg returns) and alerting patterns."""
    try:
        from src.learning.outcome_tracker import get_outcome_summary
        summary = get_outcome_summary()
    except Exception:
        summary = {"message": "No outcome data yet"}
    try:
        from src.learning.pattern_detector import get_alerts
        alerts = get_alerts()
    except Exception:
        alerts = []
    return json.dumps({"outcome_summary": summary, "alerts": alerts})


# ─── 11. Adaptive State ─────────────────────────────────────────────────────

@tool
def get_adaptive_state() -> str:
    """Get current adaptive strategy state: market regime (volatility, momentum), position sizing scalar, constraint adjustments."""
    try:
        from src.learning.adaptive import get_adaptive_state as _get
        state = _get()
        return json.dumps(state) if state else json.dumps({"message": "No adaptive state computed yet"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─── 12. Portfolio History ───────────────────────────────────────────────────

@tool
def get_portfolio_history(days: int = 90) -> str:
    """Get daily portfolio value snapshots for charting: total value, cash, positions value, benchmark value.
    Use this to answer questions about portfolio performance over time."""
    con = get_connection()
    try:
        df = con.execute("""
            SELECT snapshot_date, total_value, cash, positions_value, n_positions,
                   unrealized_pnl, total_return_pct, benchmark_value
            FROM portfolio_snapshots
            WHERE snapshot_date >= CURRENT_DATE - INTERVAL ? DAY
            ORDER BY snapshot_date ASC
        """, [days]).fetchdf()
        con.close()
        if df.empty:
            return json.dumps({"message": "No portfolio history available"})
        records = json.loads(df.to_json(orient="records", date_format="iso"))
        return json.dumps({"days": days, "snapshots": records})
    except Exception as e:
        con.close()
        return json.dumps({"error": str(e)})


# ─── 13. Price Lookup ────────────────────────────────────────────────────────

@tool
def get_stock_price(ticker: str) -> str:
    """Get the current price and recent price history for a specific stock ticker."""
    con = get_connection()
    try:
        df = con.execute("""
            SELECT date, close, volume
            FROM prices
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT 30
        """, [ticker.upper()]).fetchdf()
        con.close()
        if df.empty:
            return json.dumps({"ticker": ticker.upper(), "message": "No price data found"})
        records = json.loads(df.to_json(orient="records", date_format="iso"))
        current = records[0]["close"] if records else None
        return json.dumps({
            "ticker": ticker.upper(),
            "current_price": current,
            "recent_prices": records[:10],
            "price_30d_ago": records[-1]["close"] if len(records) >= 30 else None,
        })
    except Exception as e:
        con.close()
        return json.dumps({"error": str(e)})


# ─── 14. Fetch URL ───────────────────────────────────────────────────────────

@tool
def fetch_url(url: str) -> str:
    """Fetch the content of a URL and return the readable text.

    Use this whenever the user shares a link, asks about the contents of a
    specific webpage, or references an article. Returns up to ~8000 chars of
    extracted text (scripts, styles, and markup are stripped).
    """
    import urllib.request
    import urllib.error
    from html.parser import HTMLParser

    class _TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self._skip_depth = 0
            self._parts: list[str] = []
            self._title: str | None = None
            self._in_title = False

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "noscript", "svg"):
                self._skip_depth += 1
            elif tag == "title":
                self._in_title = True

        def handle_endtag(self, tag):
            if tag in ("script", "style", "noscript", "svg"):
                self._skip_depth = max(0, self._skip_depth - 1)
            elif tag == "title":
                self._in_title = False
            elif tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
                self._parts.append("\n")

        def handle_data(self, data):
            if self._skip_depth > 0:
                return
            stripped = data.strip()
            if not stripped:
                return
            if self._in_title and self._title is None:
                self._title = stripped
            self._parts.append(stripped + " ")

        def get_text(self) -> tuple[str | None, str]:
            raw = "".join(self._parts)
            lines = [line.strip() for line in raw.splitlines()]
            lines = [line for line in lines if line]
            return self._title, "\n".join(lines)

    try:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; Trade4MeBot/1.0; "
                    "+https://github.com/trade4me)"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read(2_000_000)  # cap at 2MB
            charset = response.headers.get_content_charset() or "utf-8"
            html_text = raw.decode(charset, errors="replace")

        parser = _TextExtractor()
        parser.feed(html_text)
        title, text = parser.get_text()

        max_chars = 8000
        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars]
            truncated = True

        return json.dumps({
            "url": url,
            "title": title,
            "content": text,
            "truncated": truncated,
        })
    except urllib.error.HTTPError as e:
        return json.dumps({"error": f"HTTP {e.code} fetching {url}: {e.reason}"})
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch {url}: {e}"})


# ─── 15. Web search ──────────────────────────────────────────────────────────

@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web (DuckDuckGo) for up-to-date information.

    Use this for questions about current events, recent news, market updates,
    or anything that requires information more recent than your training data.
    Returns a JSON list of {title, url, snippet}.
    """
    try:
        from ddgs import DDGS  # type: ignore
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # type: ignore
        except ImportError:
            return json.dumps({
                "error": "Web search unavailable: install 'ddgs' in requirements.txt."
            })

    try:
        capped = max(1, min(max_results, 10))
        with DDGS() as ddgs:
            raw_results = list(ddgs.text(query, max_results=capped))
        cleaned = [
            {
                "title": r.get("title"),
                "url": r.get("href") or r.get("url"),
                "snippet": r.get("body") or r.get("snippet"),
            }
            for r in raw_results
        ]
        return json.dumps({"query": query, "results": cleaned})
    except Exception as e:
        return json.dumps({"error": f"Search failed: {e}"})


# ─── Export all tools ────────────────────────────────────────────────────────

ALL_TOOLS = [
    get_portfolio_summary,
    get_factor_scores,
    get_trade_proposals,
    get_proposal_detail,
    get_trade_executions,
    get_judge_decisions,
    get_risk_metrics,
    get_news_research,
    get_stock_universe,
    get_learning_data,
    get_adaptive_state,
    get_portfolio_history,
    get_stock_price,
    fetch_url,
    web_search,
]
