"""Free external screener sources for stock discovery.

Three data sources, all free, using stable libraries (not raw HTML scraping):
1. Finviz — predefined stock screens (breakout, growth, value, momentum)
2. SEC EDGAR — recent material filings (8-K, 10-Q)
3. Yahoo Finance — trending/most-active tickers

Each function returns a DataFrame following the standard ingestion pattern:
graceful per-item failure, empty DataFrame on total failure.
"""

import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logger = logging.getLogger("trademark.discovery")


# ---------------------------------------------------------------------------
# 1. Finviz screener (via finvizfinance library)
# ---------------------------------------------------------------------------

FINVIZ_SCREENS = {
    "breakout": {
        "Performance": "Month +20%",
        "Average Volume": "Over 500K",
        "EPS growththis year": "Positive (>0%)",
        "Market Cap.": "+Small (over $300mln)",
    },
    "growth": {
        "EPS growththis year": "Over 20%",
        "Sales growthqtr over qtr": "Over 25%",
        "Market Cap.": "+Small (over $300mln)",
        "Price": "Over $5",
    },
    "value": {
        "P/E": "Under 15",
        "EPS growththis year": "Positive (>0%)",
        "Market Cap.": "+Mid (over $2bln)",
        "Price": "Over $10",
    },
    "momentum": {
        "20-Day Simple Moving Average": "Price above SMA20",
        "50-Day Simple Moving Average": "Price above SMA50",
        "200-Day Simple Moving Average": "Price above SMA200",
        "New 52-Week High/Low": "New High",
        "Average Volume": "Over 300K",
    },
    "speculative_growth": {
        "Market Cap.": "+Micro (over $50mln)",
        "Sales growthqtr over qtr": "Positive (>0%)",
        "Average Volume": "Over 100K",
        "Price": "Over $2",
    },
    "momentum_breakout": {
        "Performance": "Quarter +30%",
        "Average Volume": "Over 200K",
    },
}


def fetch_finviz_screen(screen_type: str = "breakout") -> pd.DataFrame:
    """Run a predefined Finviz screen and return matching tickers.

    Returns DataFrame with: ticker, company_name, sector, industry,
    market_cap, price, change_pct, volume, pe, screen_type.
    """
    filters = FINVIZ_SCREENS.get(screen_type)
    if not filters:
        logger.warning(f"Unknown screen type: {screen_type}")
        return pd.DataFrame()

    try:
        from finvizfinance.screener.overview import Overview

        screener = Overview()
        screener.set_filter(filters_dict=filters)
        df = screener.screener_view()

        if df is None or df.empty:
            return pd.DataFrame()

        col_map = {
            "Ticker": "ticker",
            "Company": "company_name",
            "Sector": "sector",
            "Industry": "industry",
            "Market Cap": "market_cap",
            "Price": "price",
            "Change": "change_pct",
            "Volume": "volume",
            "P/E": "pe",
        }
        available = {k: v for k, v in col_map.items() if k in df.columns}
        result = df.rename(columns=available)[list(available.values())].copy()
        result["screen_type"] = screen_type

        return result

    except ImportError:
        logger.warning("finvizfinance not installed — skipping Finviz screen")
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"Finviz screen '{screen_type}' failed: {e}")
        return pd.DataFrame()


def fetch_all_finviz_screens() -> pd.DataFrame:
    """Run all predefined screens and combine results."""
    frames = []
    for screen_type in FINVIZ_SCREENS:
        df = fetch_finviz_screen(screen_type)
        if not df.empty:
            frames.append(df)
        time.sleep(1)

    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    return combined.drop_duplicates(subset=["ticker"], keep="first")


# ---------------------------------------------------------------------------
# 2. SEC EDGAR recent filings (free REST API, no key needed)
# ---------------------------------------------------------------------------

EDGAR_BASE_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_FULL_TEXT = "https://efts.sec.gov/LATEST/search-index"


def fetch_recent_filings(
    form_types: list[str] | None = None,
    days: int = 7,
) -> pd.DataFrame:
    """Fetch recent SEC filings via the EDGAR full-text search API.

    Uses the free EDGAR XBRL/full-text search at efts.sec.gov.
    Rate limit: 10 requests/second. Requires User-Agent header.
    """
    if form_types is None:
        form_types = ["8-K"]

    try:
        import requests
    except ImportError:
        logger.warning("requests not installed — skipping EDGAR filings")
        return pd.DataFrame()

    headers = {
        "User-Agent": "Trademark/1.0 (collabandsave@gmail.com)",
        "Accept": "application/json",
    }

    date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    date_to = datetime.now().strftime("%Y-%m-%d")

    records = []
    for form_type in form_types:
        try:
            url = "https://efts.sec.gov/LATEST/search-index"
            params = {
                "q": f"\"form-type\":\"{form_type}\"",
                "dateRange": "custom",
                "startdt": date_from,
                "enddt": date_to,
                "forms": form_type,
            }

            # Use the simpler EDGAR company search API instead
            search_url = "https://efts.sec.gov/LATEST/search-index"
            # Fall back to the company filings API which is more reliable
            api_url = f"https://www.sec.gov/cgi-bin/browse-edgar"

            # Use the EDGAR full-text search API (most reliable free endpoint)
            ft_url = "https://efts.sec.gov/LATEST/search-index"
            ft_params = {
                "q": "*",
                "forms": form_type,
                "dateRange": "custom",
                "startdt": date_from,
                "enddt": date_to,
            }

            resp = requests.get(
                "https://efts.sec.gov/LATEST/search-index",
                params=ft_params,
                headers=headers,
                timeout=15,
            )

            if resp.status_code != 200:
                # Try the alternative EDGAR full-text search endpoint
                resp = requests.get(
                    "https://efts.sec.gov/LATEST/search-index",
                    params={"q": "*", "forms": form_type, "startdt": date_from, "enddt": date_to},
                    headers=headers,
                    timeout=15,
                )

            if resp.status_code == 200:
                data = resp.json()
                hits = data.get("hits", {}).get("hits", [])
                for hit in hits[:100]:
                    source = hit.get("_source", {})
                    tickers = source.get("tickers", [])
                    ticker = tickers[0] if tickers else source.get("ticker", "")
                    if not ticker:
                        continue
                    records.append({
                        "ticker": ticker.upper(),
                        "company_name": source.get("display_names", [""])[0] if source.get("display_names") else source.get("entity_name", ""),
                        "filing_type": form_type,
                        "filing_date": source.get("file_date", ""),
                        "description": source.get("display_date_filed", ""),
                        "url": f"https://www.sec.gov/Archives/edgar/data/{source.get('file_num', '')}",
                    })

            time.sleep(0.15)

        except Exception as e:
            logger.warning(f"EDGAR {form_type} fetch failed: {e}")
            continue

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df = df.drop_duplicates(subset=["ticker", "filing_type", "filing_date"], keep="first")
    return df


# ---------------------------------------------------------------------------
# 3. Yahoo Finance trending/most-active (via yfinance)
# ---------------------------------------------------------------------------

def fetch_yahoo_trending() -> pd.DataFrame:
    """Fetch trending and most-active tickers from Yahoo Finance.

    Uses yfinance's built-in screener capabilities.
    """
    try:
        import yfinance as yf

        records = []

        # Get most active stocks
        try:
            screener = yf.Screener()
            screener.set_predefined_body("most_actives")
            result = screener.response
            quotes = result.get("quotes", [])
            for q in quotes[:30]:
                ticker = q.get("symbol", "")
                if not ticker or "." in ticker:
                    continue
                records.append({
                    "ticker": ticker,
                    "company_name": q.get("shortName", q.get("longName", "")),
                    "sector": q.get("sector", ""),
                    "industry": q.get("industry", ""),
                    "market_cap": str(q.get("marketCap", "")),
                    "price": q.get("regularMarketPrice"),
                    "change_pct": q.get("regularMarketChangePercent"),
                    "volume": q.get("regularMarketVolume"),
                    "screen_type": "yahoo_most_active",
                })
        except Exception as e:
            logger.debug(f"Yahoo most_actives failed: {e}")

        # Get day gainers
        try:
            screener = yf.Screener()
            screener.set_predefined_body("day_gainers")
            result = screener.response
            quotes = result.get("quotes", [])
            for q in quotes[:20]:
                ticker = q.get("symbol", "")
                if not ticker or "." in ticker:
                    continue
                records.append({
                    "ticker": ticker,
                    "company_name": q.get("shortName", q.get("longName", "")),
                    "sector": q.get("sector", ""),
                    "industry": q.get("industry", ""),
                    "market_cap": str(q.get("marketCap", "")),
                    "price": q.get("regularMarketPrice"),
                    "change_pct": q.get("regularMarketChangePercent"),
                    "volume": q.get("regularMarketVolume"),
                    "screen_type": "yahoo_day_gainers",
                })
        except Exception as e:
            logger.debug(f"Yahoo day_gainers failed: {e}")

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        return df.drop_duplicates(subset=["ticker"], keep="first")

    except ImportError:
        logger.warning("yfinance not installed — skipping Yahoo trending")
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"Yahoo trending fetch failed: {e}")
        return pd.DataFrame()
