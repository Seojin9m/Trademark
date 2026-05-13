"""Enrich universe_expanded.csv with sub_sector labels via yfinance.

Reads `backend/config/universe_expanded.csv`, fetches sector + industry from
yfinance for any row with sub_sector="uncategorized", and maps to the project's
sub_sector vocabulary defined in config/settings.py.

Caches every yfinance lookup to disk so re-runs skip the network. Uses a small
thread pool because yfinance is IO-bound but rate-sensitive — too aggressive
and Yahoo starts returning empty info dicts.

Run
---
    cd backend && python -u -m scripts.enrich_universe

Optional flags via env vars:
    ENRICH_WORKERS      default 6
    ENRICH_FORCE        if set, ignore cache and refetch all
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings


CACHE_PATH = settings.paths.data_dir / "raw" / "yfinance_sectors_cache.json"
UNIVERSE_PATH = settings.paths.universe_path.parent / "universe_expanded.csv"


# --------- Mapping from yfinance (sector, industry) -> our sub_sector ---------
#
# yfinance reports sector + industry per Yahoo's taxonomy. Our internal
# sub_sector vocab (see settings.py:60) is coarser but project-specific.
# Exact-match industries take priority; sector-level fallbacks catch the rest.

INDUSTRY_TO_SUB_SECTOR: dict[str, str] = {
    # --- Technology ---
    "Semiconductors": "semiconductors",
    "Semiconductor Equipment & Materials": "semiconductors",
    "Software - Application": "cloud_software",
    "Software—Application": "cloud_software",
    "Software - Infrastructure": "cloud_software",
    "Software—Infrastructure": "cloud_software",
    "Information Technology Services": "enterprise_software",
    "Computer Hardware": "hardware",
    "Consumer Electronics": "hardware",
    "Electronic Components": "hardware",
    "Scientific & Technical Instruments": "hardware",
    "Solar": "hardware",

    # --- Communication Services ---
    "Internet Content & Information": "internet_platforms",
    "Entertainment": "media_entertainment",
    "Broadcasting": "media_entertainment",
    "Publishing": "media_entertainment",
    "Telecom Services": "telecom",
    "Electronic Gaming & Multimedia": "media_entertainment",
    "Advertising Agencies": "media_entertainment",

    # --- Healthcare ---
    "Drug Manufacturers - General": "pharma",
    "Drug Manufacturers—General": "pharma",
    "Drug Manufacturers - Specialty & Generic": "pharma",
    "Drug Manufacturers—Specialty & Generic": "pharma",
    "Biotechnology": "biotech",
    "Medical Devices": "healthcare_equipment",
    "Medical Instruments & Supplies": "healthcare_equipment",
    "Diagnostics & Research": "healthcare_equipment",
    "Healthcare Plans": "managed_care",
    "Medical Care Facilities": "healthcare_services",
    "Medical Distribution": "healthcare_services",
    "Health Information Services": "healthcare_services",
    "Pharmaceutical Retailers": "healthcare_services",

    # --- Financial Services ---
    "Banks - Diversified": "banks",
    "Banks—Diversified": "banks",
    "Banks - Regional": "banks",
    "Banks—Regional": "banks",
    "Mortgage Finance": "banks",
    "Capital Markets": "capital_markets",
    "Asset Management": "capital_markets",
    "Financial Data & Stock Exchanges": "capital_markets",
    "Insurance - Diversified": "insurance",
    "Insurance—Diversified": "insurance",
    "Insurance - Life": "insurance",
    "Insurance—Life": "insurance",
    "Insurance - Property & Casualty": "insurance",
    "Insurance—Property & Casualty": "insurance",
    "Insurance - Reinsurance": "insurance",
    "Insurance—Reinsurance": "insurance",
    "Insurance - Specialty": "insurance",
    "Insurance—Specialty": "insurance",
    "Insurance Brokers": "insurance",
    "Credit Services": "payments",
    "Financial Conglomerates": "capital_markets",
    "Shell Companies": "capital_markets",

    # --- Consumer Cyclical ---
    "Internet Retail": "retail",
    "Specialty Retail": "retail",
    "Apparel Retail": "retail",
    "Department Stores": "retail",
    "Home Improvement Retail": "retail",
    "Luxury Goods": "retail",
    "Footwear & Accessories": "retail",
    "Apparel Manufacturing": "retail",
    "Restaurants": "restaurants",
    "Auto Manufacturers": "autos",
    "Auto Parts": "autos",
    "Auto & Truck Dealerships": "autos",
    "Recreational Vehicles": "autos",
    "Lodging": "media_entertainment",
    "Travel Services": "media_entertainment",
    "Resorts & Casinos": "media_entertainment",
    "Leisure": "media_entertainment",
    "Gambling": "media_entertainment",
    "Furnishings, Fixtures & Appliances": "household_products",
    "Residential Construction": "household_products",
    "Packaging & Containers": "materials",
    "Personal Services": "household_products",
    "Textile Manufacturing": "retail",

    # --- Consumer Defensive ---
    "Beverages - Non-Alcoholic": "food_beverage",
    "Beverages—Non-Alcoholic": "food_beverage",
    "Beverages - Brewers": "food_beverage",
    "Beverages—Brewers": "food_beverage",
    "Beverages - Wineries & Distilleries": "food_beverage",
    "Beverages—Wineries & Distilleries": "food_beverage",
    "Packaged Foods": "food_beverage",
    "Confectioners": "food_beverage",
    "Food Distribution": "food_beverage",
    "Farm Products": "food_beverage",
    "Tobacco": "food_beverage",
    "Household & Personal Products": "household_products",
    "Grocery Stores": "retail",
    "Discount Stores": "retail",
    "Education & Training Services": "household_products",

    # --- Industrials ---
    "Aerospace & Defense": "aerospace_defense",
    "Specialty Industrial Machinery": "industrial_machinery",
    "Farm & Heavy Construction Machinery": "industrial_machinery",
    "Industrial Distribution": "industrial_machinery",
    "Tools & Accessories": "industrial_machinery",
    "Metal Fabrication": "industrial_machinery",
    "Pollution & Treatment Controls": "industrial_machinery",
    "Electrical Equipment & Parts": "industrial_machinery",
    "Specialty Business Services": "industrial_machinery",
    "Staffing & Employment Services": "industrial_machinery",
    "Consulting Services": "industrial_machinery",
    "Security & Protection Services": "industrial_machinery",
    "Rental & Leasing Services": "industrial_machinery",
    "Engineering & Construction": "industrial_machinery",
    "Infrastructure Operations": "industrial_machinery",
    "Building Products & Equipment": "industrial_machinery",
    "Conglomerates": "industrial_machinery",
    "Waste Management": "industrial_machinery",
    "Business Equipment & Supplies": "industrial_machinery",
    "Railroads": "transports",
    "Trucking": "transports",
    "Airlines": "transports",
    "Marine Shipping": "transports",
    "Integrated Freight & Logistics": "transports",
    "Airports & Air Services": "transports",

    # --- Energy ---
    "Oil & Gas Integrated": "energy_majors",
    "Oil & Gas E&P": "energy_majors",
    "Oil & Gas Refining & Marketing": "energy_majors",
    "Thermal Coal": "energy_majors",
    "Uranium": "energy_majors",
    "Oil & Gas Midstream": "midstream",
    "Oil & Gas Equipment & Services": "oil_services",
    "Oil & Gas Drilling": "oil_services",

    # --- Utilities ---
    "Utilities - Regulated Electric": "utilities",
    "Utilities—Regulated Electric": "utilities",
    "Utilities - Regulated Gas": "utilities",
    "Utilities—Regulated Gas": "utilities",
    "Utilities - Regulated Water": "utilities",
    "Utilities—Regulated Water": "utilities",
    "Utilities - Diversified": "utilities",
    "Utilities—Diversified": "utilities",
    "Utilities - Independent Power Producers": "utilities",
    "Utilities—Independent Power Producers": "utilities",
    "Utilities - Renewable": "utilities",
    "Utilities—Renewable": "utilities",

    # --- Real Estate ---
    "REIT - Diversified": "reits",
    "REIT—Diversified": "reits",
    "REIT - Healthcare Facilities": "reits",
    "REIT—Healthcare Facilities": "reits",
    "REIT - Hotel & Motel": "reits",
    "REIT—Hotel & Motel": "reits",
    "REIT - Industrial": "reits",
    "REIT—Industrial": "reits",
    "REIT - Mortgage": "reits",
    "REIT—Mortgage": "reits",
    "REIT - Office": "reits",
    "REIT—Office": "reits",
    "REIT - Residential": "reits",
    "REIT—Residential": "reits",
    "REIT - Retail": "reits",
    "REIT—Retail": "reits",
    "REIT - Specialty": "reits",
    "REIT—Specialty": "reits",
    "Real Estate - Development": "reits",
    "Real Estate—Development": "reits",
    "Real Estate - Diversified": "reits",
    "Real Estate—Diversified": "reits",
    "Real Estate Services": "reits",

    # --- Basic Materials ---
    "Specialty Chemicals": "materials",
    "Chemicals": "materials",
    "Agricultural Inputs": "materials",
    "Steel": "materials",
    "Copper": "materials",
    "Aluminum": "materials",
    "Gold": "materials",
    "Silver": "materials",
    "Other Industrial Metals & Mining": "materials",
    "Other Precious Metals & Mining": "materials",
    "Coking Coal": "materials",
    "Building Materials": "materials",
    "Lumber & Wood Production": "materials",
    "Paper & Paper Products": "materials",
}

# Sector-level fallback when industry doesn't match anything specific.
SECTOR_FALLBACK: dict[str, str] = {
    "Technology": "enterprise_software",
    "Communication Services": "media_entertainment",
    "Healthcare": "pharma",
    "Financial Services": "capital_markets",
    "Consumer Cyclical": "retail",
    "Consumer Defensive": "food_beverage",
    "Industrials": "industrial_machinery",
    "Energy": "energy_majors",
    "Utilities": "utilities",
    "Real Estate": "reits",
    "Basic Materials": "materials",
}


def map_to_sub_sector(sector: str | None, industry: str | None) -> str:
    if industry and industry in INDUSTRY_TO_SUB_SECTOR:
        return INDUSTRY_TO_SUB_SECTOR[industry]
    if sector and sector in SECTOR_FALLBACK:
        return SECTOR_FALLBACK[sector]
    return "uncategorized"


def load_simfin_sector_lookup() -> dict[str, dict[str, str]]:
    """Build {ticker -> {sector, industry}} from SimFin's bulk companies data.

    Uses the same bulk CSVs that fundamentals.py downloads — already cached
    locally, so this is essentially free. Returns empty dict if SimFin data
    isn't available (no API key, network down, etc.).
    """
    try:
        import simfin as sf
    except ImportError:
        return {}

    try:
        sf.set_api_key(settings.api_keys.simfin_api_key)
        sf.set_data_dir(str(settings.paths.fundamentals_raw_dir))
        companies = sf.load_companies(market="us")
        industries = sf.load_industries()
    except Exception as e:
        print(f"  WARNING: SimFin lookup failed: {e}")
        return {}

    # SimFin uses 'IndustryId' as the join key; load_industries returns
    # Sector + Industry columns indexed by IndustryId.
    companies = companies.reset_index()
    industries = industries.reset_index()
    merged = companies.merge(industries, on="IndustryId", how="left")

    out: dict[str, dict[str, str]] = {}
    for _, row in merged.iterrows():
        t = row.get("Ticker")
        if not isinstance(t, str):
            continue
        out[t] = {
            "sector": row.get("Sector") or None,
            "industry": row.get("Industry") or None,
        }
    return out


def load_cache() -> dict[str, dict]:
    if CACHE_PATH.exists():
        with open(CACHE_PATH) as f:
            return json.load(f)
    return {}


def save_cache(cache: dict[str, dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(cache, f)
    tmp.replace(CACHE_PATH)


def fetch_one(ticker: str) -> tuple[str, dict]:
    """Returns (ticker, {sector, industry, error}). Never raises."""
    import yfinance as yf

    try:
        info = yf.Ticker(ticker).info or {}
        return ticker, {
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }
    except Exception as e:
        return ticker, {"error": str(e)[:200]}


def main() -> None:
    workers = int(os.getenv("ENRICH_WORKERS", "6"))
    force = bool(os.getenv("ENRICH_FORCE"))

    df = pd.read_csv(UNIVERSE_PATH)
    print(f"Loaded {len(df)} tickers from {UNIVERSE_PATH}")

    cache = {} if force else load_cache()
    print(f"Cache: {len(cache)} entries")

    # Decide which tickers actually need a network call. Anything already
    # categorized stays as-is; anything in cache with usable sector/industry
    # uses the cache; rate-limited or empty entries get retried.
    def _cache_entry_is_usable(entry: dict) -> bool:
        if entry.get("error"):
            return False
        sector = entry.get("sector")
        industry = entry.get("industry")
        # Empty strings and None both count as "no useful data"
        return bool((sector and sector.strip()) or (industry and industry.strip()))

    needs_fetch: list[str] = []
    for _, row in df.iterrows():
        t = row["ticker"]
        if row["sub_sector"] != "uncategorized":
            continue  # already curated
        if not force and t in cache and _cache_entry_is_usable(cache[t]):
            continue
        needs_fetch.append(t)

    print(f"To fetch: {len(needs_fetch)} tickers (workers={workers})")

    if needs_fetch:
        t0 = time.time()
        completed = 0
        # Periodically flush cache so a crash mid-run doesn't lose progress.
        FLUSH_EVERY = 100
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(fetch_one, t): t for t in needs_fetch}
            for fut in as_completed(futures):
                ticker, info = fut.result()
                cache[ticker] = info
                completed += 1
                if completed % 50 == 0 or completed == len(needs_fetch):
                    rate = completed / max(time.time() - t0, 0.001)
                    eta = (len(needs_fetch) - completed) / max(rate, 0.001)
                    print(
                        f"  {completed}/{len(needs_fetch)} "
                        f"({rate:.1f}/s, ETA {eta:.0f}s)"
                    )
                if completed % FLUSH_EVERY == 0:
                    save_cache(cache)
        save_cache(cache)
        print(f"Network fetch done in {time.time() - t0:.0f}s")

    # SimFin fallback: cheap (already cached on disk via fundamentals.py)
    # and gives us sector/industry for ~3000 US tickers. Only consulted when
    # yfinance returns nothing usable — yfinance's industry taxonomy is
    # finer-grained, so prefer it when both are present.
    print("\nLoading SimFin sector lookup as fallback...")
    simfin_lookup = load_simfin_sector_lookup()
    print(f"  SimFin has sector data for {len(simfin_lookup)} tickers")

    # Apply mapping. Track stats and which source resolved each ticker so
    # we can sanity-check the breakdown afterward.
    sector_distribution: dict[str, int] = {}
    source_counts = {"curated": 0, "yfinance": 0, "simfin": 0, "uncategorized": 0}

    def _resolve(row: pd.Series) -> str:
        if row["sub_sector"] != "uncategorized":
            source_counts["curated"] += 1
            return row["sub_sector"]
        t = row["ticker"]
        info = cache.get(t, {})
        sub = map_to_sub_sector(info.get("sector"), info.get("industry"))
        if sub != "uncategorized":
            source_counts["yfinance"] += 1
            return sub
        sf_info = simfin_lookup.get(t, {})
        sub = map_to_sub_sector(sf_info.get("sector"), sf_info.get("industry"))
        if sub != "uncategorized":
            source_counts["simfin"] += 1
            return sub
        source_counts["uncategorized"] += 1
        return "uncategorized"

    df["sub_sector"] = df.apply(_resolve, axis=1)

    for s in df["sub_sector"]:
        sector_distribution[s] = sector_distribution.get(s, 0) + 1

    df.to_csv(UNIVERSE_PATH, index=False)
    print(f"\nWrote enriched universe to {UNIVERSE_PATH}")
    print(f"\n=== Resolution source ===")
    for src, n in source_counts.items():
        print(f"  {src:14s} {n:>5d}")

    print("\n=== Sub-sector distribution ===")
    for sub, n in sorted(sector_distribution.items(), key=lambda kv: -kv[1]):
        print(f"  {sub:24s} {n:>5d}")
    new_uncategorized = source_counts["uncategorized"]
    print(f"\nStill uncategorized: {new_uncategorized}")
    if new_uncategorized > 0:
        # Print a few examples so the user can see what's slipping through
        miss = df[df["sub_sector"] == "uncategorized"].head(15)
        print("Sample uncategorized tickers (with raw yf data):")
        for _, row in miss.iterrows():
            info = cache.get(row["ticker"], {})
            print(
                f"    {row['ticker']:6s} "
                f"sector={info.get('sector')!r} "
                f"industry={info.get('industry')!r} "
                f"err={info.get('error')!r}"
            )


if __name__ == "__main__":
    main()
