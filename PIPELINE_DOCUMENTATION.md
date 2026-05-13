# Trademark Pipeline — Complete Technical Documentation

> **One-read guide** to every process, calculation, formula, and decision in the Trademark stock analysis pipeline. Written for export and offline reference.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Data Ingestion](#2-data-ingestion)
3. [Factor Computation](#3-factor-computation)
4. [Composite Scoring Engine](#4-composite-scoring-engine)
5. [Signal Generation (Decision Rules)](#5-signal-generation-decision-rules)
6. [Portfolio Construction](#6-portfolio-construction)
7. [LLM Judge Layer](#7-llm-judge-layer)
8. [Adaptive Self-Learning System](#8-adaptive-self-learning-system)
9. [Signal Quality Tracker](#9-signal-quality-tracker)
10. [Universe Management & Discovery](#10-universe-management--discovery)
11. [Risk Profiles](#11-risk-profiles)
12. [Pipeline Execution Order](#12-pipeline-execution-order)
13. [Key Configuration Parameters](#13-key-configuration-parameters)

---

## 1. System Overview

Trademark is a quantitative stock analysis pipeline that:

1. **Ingests** daily prices, quarterly fundamentals, and analyst estimates for ~224 tickers
2. **Scores** every stock on 6 factors (momentum, EPS growth, revenue growth, margins, valuation, forward estimates)
3. **Generates** BUY / SELL / HOLD / TRIM / ADD signals using a value-investing framework
4. **Validates** every trade proposal through a Claude AI judge that reviews news, technicals, and historical patterns
5. **Learns** from its own outcomes — adjusting factor weights, detecting regime changes, and flagging decaying signals

The pipeline runs as a FastAPI server with a React frontend. All data lives in a local DuckDB database. The judge audit trail uses a separate SQLite file.

### Core Philosophy

- **Quality first, price second.** A stock must pass the quality gate (good fundamentals) before price dip can make it a buy candidate. A bad stock with a cheap price is NOT a buy signal.
- **No chasing.** Stocks that have already run up get penalized or skipped entirely, depending on risk profile.
- **Anti-whipsaw.** Minimum holding periods and trade cooldowns prevent selling a stock you just bought because the model fluctuated.
- **Human-in-the-loop.** The pipeline pauses at review gates (scoring, signals, proposals, research, judge). A human can override, exclude, or approve at each stage.

---

## 2. Data Ingestion

### 2.1 Price Data

**Sources:** Polygon.io (daily EOD, primary), yfinance (historical backfill)

**Process:**
1. Load ticker list from `config/universe.csv`
2. Check if today's prices already exist in DuckDB (5-day lookback window, requires ≥50 tickers)
3. If not, fetch from Polygon's Grouped Daily endpoint (single API call for all US stocks, then filter to our universe)
4. Missing tickers fall back to per-ticker Polygon fetch with 61-second rate-limit pauses every 5 tickers
5. Store to `prices` table: `(ticker, date, open, high, low, close, volume, adj_close)`

**Historical backfill:** yfinance bulk download from 2016-01-01 with `auto_adjust=True` (close = adjusted close). Used for initial setup only.

### 2.2 Quarterly Fundamentals

**Sources:** Simfin (primary, free tier), yfinance (fallback for gaps)

**Process:**
1. Check ingestion cooldown: skip if last ingestion was < 14 days ago
2. Download quarterly income statements from Simfin (3 datasets: general, banks, insurance — because banks/insurers have different financial structures)
3. Download quarterly balance sheets from Simfin
4. Identify "thin" tickers — stocks where Simfin data is incomplete or stale:
   - Fewer than 5 quarters available (can't compute YoY growth)
   - Newest quarter is >270 days behind the dataset's overall newest (fell off Simfin's refresh)
   - Newest quarter is >150 days behind today's date (absolute staleness — catches cases where the whole Simfin dataset is lagging)
5. For thin tickers: fetch from yfinance as fallback (quarterly_income_stmt, quarterly_balance_sheet)
6. Tag all data with **Point-in-Time (PIT)** dates — uses the Report Date (when the filing was publicly available), NOT the Fiscal Period End date. This prevents look-ahead bias: we never use data that wasn't public yet on the scoring date.
7. Store to `fundamentals_pit` table: `(ticker, fiscal_period_end, report_date, revenue, gross_profit, net_income, eps_diluted, shares_outstanding, ...)`

**PIT lag for yfinance:** Yahoo doesn't expose the actual publish date, so we add a 50-day proxy lag (conservative enough to cover typical 10-Q filing windows).

### 2.3 Forward Analyst Estimates

**Source:** yfinance (`.analyst_price_targets`, `.earnings_estimate`, `.growth_estimates`, `.info`)

**Cooldown:** 7 days (analyst estimates change weekly, not daily)

**Process:**
1. Check `ingestion_log` for 7-day cooldown
2. For each ticker, fetch from yfinance:
   - EPS estimates: current quarter, next quarter, current year, next year
   - Number of covering analysts
   - Price target: mean, high, low, current
   - Growth estimate for next year
   - Mean recommendation (1=Strong Buy to 5=Strong Sell)
3. Rate-limited: 0.3-second sleep every 10 tickers
4. Store to `forward_estimates` table: `(ticker, fetch_date, eps_est_current_q, eps_est_next_q, eps_est_current_y, eps_est_next_y, num_analysts, price_target_mean, ...)`

### 2.4 Earnings Calendar

**Source:** yfinance earnings calendar

Stores upcoming earnings dates, EPS estimates, and actuals. Used for:
- **Timing signals:** penalize trades near binary earnings events
- **Surprise detection:** identify earnings beats >5% for discovery

---

## 3. Factor Computation

Every stock is scored on **6 factors**. Each factor produces a raw value that is later z-scored and weighted.

### 3.1 Momentum (12M-1M)

**What it measures:** Medium-term price trend, excluding the most recent month.

**Formula:**
```
momentum_12m1m = (price_1_month_ago / price_12_months_ago) - 1
```

In plain English: how much did the stock go up from 12 months ago to 1 month ago? We skip the last month to avoid short-term mean reversion noise.

**Implementation details:**
- "12 months" = 252 trading days (or the oldest available bar if the stock has <252 days of history)
- "1 month" = 21 trading days
- Stocks need at least 22 trading days of history to be scored
- In HIGH_VOL regime (see Section 8), the long anchor shrinks to 126 days (6 months) — momentum signals are less reliable over long periods in volatile markets

**Recent price change (auxiliary):**
```
recent_price_change = (price_now / price_1_month_ago) - 1
```

**Price dip score (auxiliary):**
```
price_dip_score = -recent_price_change, clipped to [-0.3, +0.3]
```
A stock that dropped 10% last month → dip score = +0.10 (opportunity).
A stock that rose 10% → dip score = -0.10 (chase risk).

The price dip score is NOT a factor itself — it's used in Stage 2 of composite scoring (Section 4).

**Default weight:** 15%

### 3.2 EPS Growth (Year-over-Year)

**What it measures:** Is the company earning more per share than a year ago?

**Formula (primary — when ≥5 quarters available):**
```
eps_growth_yoy = (EPS_most_recent_quarter / EPS_same_quarter_last_year) - 1
```

**Fallback (2-3 quarters only):** Average sequential quarter-over-quarter growth:
```
For each consecutive pair of quarters:
    qoq_growth = (EPS_current / EPS_prior) - 1    (only if |EPS_prior| > 0.01)
eps_growth_yoy = mean(all qoq_growth values)
```

**Clipping:** Result is clipped to [-5.0, +10.0] to prevent outliers from dominating.

**Data source:** `fundamentals_pit` table, PIT-safe (only uses data published before the scoring date).

**Default weight:** 15%

### 3.3 Revenue Growth (Year-over-Year)

**What it measures:** Is the company's top-line growing?

**Formula:** Same structure as EPS Growth, but using revenue instead of EPS:
```
revenue_growth_yoy = (Revenue_most_recent_quarter / Revenue_same_quarter_last_year) - 1
```

**Fallback:** Sequential QoQ average, same as EPS Growth.

**Clipping:** [-2.0, +10.0]

**Default weight:** 15%

### 3.4 Gross Margin Trend

**What it measures:** Are profit margins expanding or contracting?

**Formula (when ≥4 quarters available):**
```
margin_recent = gross_profit_last_2_quarters / revenue_last_2_quarters
margin_prior  = gross_profit_prior_2_quarters / revenue_prior_2_quarters
gross_margin_trend = margin_recent - margin_prior
```

**Fallback (2-3 quarters):**
```
margin_now   = gross_profit_Q0 / revenue_Q0
margin_prior = gross_profit_Q1 / revenue_Q1
gross_margin_trend = margin_now - margin_prior
```

In plain English: a positive value means margins are getting better. A value of 0.02 means margins improved by 2 percentage points.

**Clipping:** [-0.5, +0.5]

**Note:** Banks and insurance companies don't report gross profit. Their gross_margin_trend will be NaN, and the composite scoring engine renormalizes the remaining factor weights for these tickers.

**Default weight:** 10%

### 3.5 Relative Valuation (P/S vs. Sector Peers)

**What it measures:** Is this stock cheap or expensive compared to its sub-sector peers?

**Formula:**
```
ps_ratio = (price × shares_outstanding) / ttm_revenue
sector_median_ps = median(ps_ratio for all stocks in same sub_sector)
relative_valuation = -(log(ps_ratio) - log(sector_median_ps))
```

The negative sign inverts the score: **cheap stocks (low P/S) get positive scores.**

In plain English: if a stock's P/S ratio is half its sector median, the log difference is about -0.69, and after negation the score is +0.69. A positive score means "cheaper than peers."

**Clipping:** [-3.0, +3.0]

**Why P/S instead of P/E?** P/S works for unprofitable companies (which have no meaningful P/E). The forward P/E is now captured separately in the Forward Estimates factor.

**Default weight:** 20%

### 3.6 Forward Estimate Revision

**What it measures:** Are analysts becoming more optimistic or pessimistic about this stock?

This is a **blended factor** combining three sub-signals:

#### Sub-signal 1: EPS Revision Momentum (40% of blend)
```
eps_revision = (current_est_next_year - prior_est_next_year) / |prior_est_next_year|
```
"Prior" = the estimate from 28 days ago. A positive value means analysts are raising their earnings forecasts.

**Clipping:** [-2.0, +2.0]

#### Sub-signal 2: Forward P/E Discount vs. Sector (30% of blend)
```
forward_pe = price / eps_estimate_next_year
sector_median_pe = median(forward_pe for same sub_sector)
forward_pe_discount = -(log(forward_pe) - log(sector_median_pe))
```
Same logic as Relative Valuation but using forward (estimated) earnings instead of trailing sales. Cheaper forward P/E = higher score.

**Clipping:** [-3.0, +3.0]. Only computed when eps_estimate_next_year > 0.01.

#### Sub-signal 3: Price Target Upside (30% of blend)
```
price_target_upside = (mean_analyst_price_target - current_price) / current_price
```
If analysts think the stock is worth 20% more → upside = +0.20.

**Clipping:** [-1.0, +1.0]

#### Blending
Each sub-signal is **z-scored cross-sectionally** (mean=0, std=1 across all stocks). Then:
```
forward_estimate_revision = Σ(z_score_i × weight_i) / Σ(weight_i)
```
Where weights are `{eps_revision: 0.40, forward_pe_discount: 0.30, price_target_upside: 0.30}`. If a sub-signal is missing for a ticker (no analyst coverage), the weights are renormalized over the available sub-signals.

**Default weight:** 25% (strongest alpha signal in quantitative equity research)

---

## 4. Composite Scoring Engine

The scoring engine combines all 6 factors into a single composite score using a **two-stage process**: quality first, then price adjustment.

### 4.1 Data Preparation

1. **Merge all factor DataFrames** into one table by ticker
2. **Load user overrides** from `stock_metrics` table (if a user manually corrected a metric value, use that instead of the computed value)
3. **Merge sub-sector** from `universe.csv` for sector-neutral scoring

### 4.2 Winsorization

Before z-scoring, each factor is **winsorized** at ±3 standard deviations:
```
lower_bound = mean - 3 × std
upper_bound = mean + 3 × std
capped_value = clip(raw_value, lower_bound, upper_bound)
```
This prevents extreme outliers (e.g., a stock with 5000% revenue growth) from distorting the cross-sectional distribution.

### 4.3 Sector-Neutral Z-Scoring

Each factor is z-scored using a blend of **within-sector** and **global** z-scores:

```
global_z = (value - global_mean) / global_std
sector_z = (value - sector_mean) / sector_std
final_z  = blend × sector_z + (1 - blend) × global_z
```

**Default blend = 1.0** (pure sector-neutral). This means a semiconductor stock is compared against other semiconductor stocks, not against banks.

**Minimum group size = 5.** Sub-sectors with fewer than 5 stocks fall back to global z-scoring because z-scores on tiny groups are noisy.

### 4.4 Stage 1: Quality Assessment (Before Price)

The quality score uses only fundamental factors — **NOT momentum**. This is the core value-investing principle: determine if the stock is good BEFORE looking at its price.

**Quality factors:** eps_growth_yoy, revenue_growth_yoy, gross_margin_trend, relative_valuation, forward_estimate_revision

**Formula:**
```
quality_score = Σ(z_score_i × weight_i) / Σ(weight_i for non-NaN factors)
```

Then the **PER penalty** is applied:

#### P/E Ratio Filter
```
per_ratio = price / (ttm_net_income / shares_outstanding)
per_vs_peer = per_ratio / sector_median_per
```

- **Absolute check:** Is P/E > 40? (configurable via `max_absolute_per`)
- **Relative check:** Is P/E > 1.5× sector median? (configurable via `max_relative_per_vs_peer`)

**PER penalty (softened — high-growth stocks can still pass):**
```
If P/E > 40:   penalty -= clip((per_ratio - 40) / 80, 0, 1.0)
If P/E > 1.5× peer:  penalty -= clip((per_vs_peer - 1.5) / 3.0, 0, 0.75)
```

The denominator is doubled (2× the threshold) so the penalty ramps slowly. A stock with P/E=50 gets only a -0.125 penalty, not a disqualification.

**Good stock determination:**
```
quality_score_adjusted = quality_score + per_penalty
is_good_stock = (quality_score_adjusted >= min_quality_zscore)
```
Default `min_quality_zscore = -0.5`. A stock can have slightly below-average quality and still be "good" — the threshold is not demanding.

### 4.5 Stage 2: Price-Adjusted Composite Score

Now the full composite score includes momentum:

```
base_composite = Σ(z_score_i × weight_i) / Σ(weight_i)    [all 6 factors]
base_composite += per_penalty
```

**Price opportunity adjustment:**
- Good stock with price dip (dip > 0): `bonus = price_dip_score × 0.5` (up to +0.15)
- Good stock with price rise (dip < 0): `penalty = price_dip_score × 0.5` (up to -0.15)
- Bad stock with price dip: **NO bonus** (bad stock + cheap price ≠ buy signal)
- Bad stock with price rise: `penalty = price_dip_score × 0.3`

```
composite_score = base_composite + price_opportunity_adjustment
```

### 4.6 Decile Assignment

Stocks are ranked by composite_score and assigned to **deciles 1-10** (1=worst, 10=best):
```
percentile_rank = rank(composite_score, method='first', pct=True)
score_decile = ceil(percentile_rank × 10), clipped to [1, 10]
```

A decile-10 stock is in the top 10% of the universe.

---

## 5. Signal Generation (Decision Rules)

The decision rules engine converts scores into actionable signals: BUY, SELL, HOLD, TRIM, ADD.

### 5.1 Key Parameters (from Risk Profile)

| Parameter | What it controls |
|-----------|-----------------|
| `buy_min_decile` | Minimum decile to be a BUY candidate (default: 8) |
| `min_decile_change` | How much the decile must change from prior run to trigger a trade (default: 2) |
| `chase_threshold` | Maximum recent price rise before chase penalty kicks in (default: 5%) |
| `chase_mode` | How to handle chasing: "strict" (block), "gradient" (reduce size), "allow" |
| `max_single_position` | Maximum weight for any single stock (default: 10%) |
| `drawdown_alert` | Portfolio drawdown that blocks new buys (default: -15%) |
| `drawdown_halt` | Portfolio drawdown that blocks ALL trades (default: -20%) |

### 5.2 Processing Existing Holdings

For each stock currently in the portfolio:

**If the stock is a GOOD stock (is_good_stock = True):**
- The system has a **high bar to sell.** Value investing principle: don't sell winners because the price dropped. A good stock at a low decile means momentum reversed — that's a dip opportunity, not a sell signal.
- If decile is high AND rising → **ADD** (increase position). Size depends on:
  - Price recently dipped → strong add (up to 1.7× current weight)
  - Price recently rose above chase threshold → cautious add or HOLD (avoid chasing)
  - Normal conditions → moderate add (up to 1.5× current weight)
- Otherwise → **HOLD** with note about quality

**If the stock is a BAD stock (is_good_stock = False):**
- Standard sell discipline applies:
  - Decile ≤ 2 AND decile dropped by ≥threshold → **SELL** (full exit)
  - Decile ≤ 4 AND decile dropped by ≥threshold → **TRIM** (reduce to 50%)
  - Otherwise → **HOLD** (change too small to act on)

### 5.3 Anti-Whipsaw Protection

**Minimum holding period** (default: 20 days): A stock bought fewer than 20 days ago cannot be sold, regardless of score changes.

**Cooldown window** (default: 40 days = 2× min holding): Between day 20 and day 40, the decile-change threshold is gradually raised (up to 2× the base threshold), making it harder to reverse a recent trade.

**Trade count cap:** If a ticker has been traded ≥3 times in the last 30 days, it's blocked from new trades.

### 5.4 Processing Non-Holdings (BUY Candidates)

For stocks NOT currently in the portfolio:

1. **Quality gate:** Must be `is_good_stock = True`. Bad stocks are never buy candidates.
2. **Risk tier gate:** The stock's risk tier (standard/moderate_risk/high_risk) must be in the allowed list for the current risk level.
3. **Anti-whipsaw:** If this stock was sold fewer than 20 days ago, skip it.
4. **Trade count:** If traded ≥3 times in 30 days, skip it.
5. **Decile gate:** Must be ≥ `buy_min_decile` (default 8) AND decile must have risen by ≥ `min_decile_change` (default 2).

**Position sizing for new buys:**
```
base_weight = 6%
```
- Price recently dipped → `dip_bonus = min(|recent_change| × 0.5, 3%)`, so weight up to 9%
- Price rose above chase threshold → apply chase multiplier:
  - Strict mode: multiplier = 0 (skip the trade)
  - Gradient mode: `multiplier = max(0, 1 - (excess_rise / 10%))` — gradual reduction
  - Allow mode: multiplier = 1 (no penalty)
- Final weight: `base_weight × effective_scalar × chase_multiplier`

**Earnings timing penalty:**
- Earnings in ≤2 days → position halved (50%), flagged as binary event risk
- Earnings in ≤7 days → position reduced 25%

### 5.5 Volatility-Adjusted Position Sizing

When adaptive parameters are available, buy positions are adjusted by **inverse volatility**:
```
ann_vol = std(log_returns) × √252    [63-day lookback]
inv_vol_ratio = (1/ticker_vol) / (mean(1/all_vols))
adjusted_weight = base_weight × clip(inv_vol_ratio, 0.5, 2.0) × vol_scalar
```
Low-volatility stocks get up to 2× the weight. High-volatility stocks get down to 0.5×. This ensures similar risk contribution from each position.

### 5.6 Correlation-Aware Deduplication

Among buy candidates, the system checks pairwise correlations (63-day log-return correlation):
- Correlation > 0.85 → the lower-scoring candidate is **removed** (not just penalized — eliminated)
- Correlation 0.70-0.85 with an existing holding → position weight reduced to 75%
- Correlation > 0.85 with an existing holding → position weight reduced to 50%

### 5.7 Rotation

If there are buy candidates but no cash, the system looks for **weak holdings** to fund the buys:
- A holding is "weak" if: decile ≤ 4, is_good_stock = False, and it wasn't recently bought (cooldown)
- The weakest holding gets **trimmed to 50%** to free up cash for the strongest buy candidate
- Only happens when the buy candidate's composite score exceeds the weak holding's score + 0.1

### 5.8 Trade Caps

| Cap | Default |
|-----|---------|
| Max new BUY positions per run | 3 |
| Max total trades per run | 5 |

Both caps are adjustable per regime (see Section 8).

---

## 6. Portfolio Construction

### 6.1 Constraint Checks

Every trade proposal goes through constraint validation:

| Constraint | Default Limit |
|-----------|--------------|
| Max single position weight | 10% |
| Min position size | 1% |
| Max positions in portfolio | 25 |
| Min positions | 8 |
| Max sub-sector weight | 50% per sub-sector |
| Cash sufficiency | Must have enough cash for BUY |

Sub-sector caps are adaptive: if a sub-sector has a historically poor win rate (<40% over ≥5 trades), the cap is tightened by a multiplier (`max(0.5, win_rate / 0.50)`).

### 6.2 Trade Proposal Generation

Signals are converted to proposals with:
```
current_value = current_weight × portfolio_value
target_value  = target_weight × portfolio_value
delta_value   = target_value - current_value
shares_to_trade = int(delta_value / current_price)
```
Proposals with 0 shares (e.g., price too high for the target allocation) are dropped.

**Cash-capped BUY ordering:** BUY proposals are sorted by composite score (best first) and capped by available cash. If you have $5,000 in cash and the top 3 buys need $3,000, $2,500, and $4,000, only the first two are included.

---

## 7. LLM Judge Layer

Every trade proposal (or the full portfolio when no trades are proposed) is evaluated by a Claude AI judge.

### 7.1 Judge Input

The judge receives a structured payload containing:
- **Evaluation context:** portfolio value, drawdown from peak, cash percentage
- **Proposed trade:** ticker, action, shares, current/proposed weight, estimated cost
- **Signal context:** composite score, decile, prior decile, all 6 factor scores, reason text
- **Constraint check:** pass/fail, list of violations
- **Recent news:** AI-summarized headlines, sentiment, risk factors, opportunities, binary events
- **Competitive intelligence:** peer comparison, sector sentiment, earnings spillover
- **Price & technical context:** support/resistance, RSI, volume patterns
- **Historical context:** similar past decisions and their outcomes, overall win rate, sector win rate
- **Earnings timing:** upcoming earnings date and EPS estimate
- **Market regime:** volatility level, momentum trend
- **Risk posture instruction:** calibrated to the user's risk level (1-5)
- **User notes:** any context the user provided (with objectivity framing — the judge is told to weigh user notes against quantitative data)
- **Analyst guidance:** if an analyst review is active, its recommendations are injected

### 7.2 Judge Output

The judge returns:
```json
{
  "verdict": "approve" | "reject" | "needs_review",
  "confidence": 0.0 - 1.0,
  "reasons": ["..."],
  "violated_rules": ["..."],
  "risk_flags": ["..."],
  "binary_event_warning": true/false,
  "data_quality_concerns": ["..."]
}
```

### 7.3 Judge Configuration

| Setting | Value |
|---------|-------|
| Model | claude-sonnet-4-6 |
| Temperature | 0.0 (deterministic) |
| Max tokens | 1,024 per proposal, 4,096 for portfolio review |

### 7.4 Portfolio Review (No-Trade Case)

When the pipeline generates zero actionable signals, the judge doesn't skip — it runs a **full portfolio review**:
- Evaluates every current holding
- Reviews top-scoring stocks not in the portfolio
- Returns whether it **agrees** or **disagrees** with holding everything
- Identifies missed opportunities and risk flags

### 7.5 Audit Trail

Every judge call is logged to `logs/judge_log.db` (SQLite) with:
- Full input payload, output payload, verdict, confidence, model used, input hash
- Immutable — entries are never updated or deleted

---

## 8. Adaptive Self-Learning System

The adaptive system automatically adjusts strategy parameters based on market conditions and historical performance.

### 8.1 Regime Detection

**Input:** Last 63 days of benchmark (SPY) prices

**Volatility regime:**
```
realized_vol = std(daily_returns) × √252    [annualized]

If realized_vol < 12%:  LOW_VOL
If realized_vol > 25%:  HIGH_VOL
Otherwise:              NORMAL
```

**Momentum regime:**
```
momentum_21d = (price_today / price_21_days_ago) - 1

If momentum_21d > +3%:  BULL
If momentum_21d < -3%:  BEAR
Otherwise:              SIDEWAYS
```

### 8.2 Factor Weight Optimization (IC-Based)

**What is IC?** Information Coefficient = Spearman rank correlation between a factor's score today and the stock's 21-day forward return. A factor with high positive IC is predictive — stocks it ranks highly actually go up more.

**Process:**
1. For each scoring date in the last 126 days (6 months):
   - Get each stock's factor score on that date
   - Get each stock's actual return over the next 21 days
   - Compute Spearman correlation = IC for that date
2. Average the ICs across all dates → `avg_ic` per factor
3. Compute t-statistic: `t = avg_ic / (ic_std / √n)`. Significant if |t| > 1.96 (95% confidence).

**IC-optimal weights:**
```
ic_weight[factor] = max(avg_ic, 0) / sum(all max(avg_ic, 0))
```
Only positive IC counts. A factor with negative IC (anti-predictive) gets zero weight.

**Bayesian shrinkage (conservative blending):**
```
equal_weight = 1/6 ≈ 0.167
shrunk_weight = 0.5 × ic_weight + 0.5 × equal_weight
```
The 0.5 shrinkage strength means we only move halfway from equal-weight toward IC-optimal. This prevents overfitting to noisy IC estimates.

**Bear market override:** In BEAR + HIGH_VOL regime, 5% is shifted from momentum to valuation (momentum reversals are likely in crashes).

### 8.3 Adaptive Constraint Tuning

| Regime | Decile Threshold | Position Size | Max New Positions |
|--------|-----------------|---------------|-------------------|
| HIGH_VOL | ≥3 (require stronger conviction) | 50%-100% (reduced) | base - 1 |
| NORMAL | base (2) | 100% | base (3) |
| LOW_VOL | base - 1 (1) (capture more) | 100%-150% (increased) | base + 1 (in BULL) |

**Volatility targeting:**
```
target_vol = 18%
vol_scalar = clip(target_vol / realized_vol, 0.5, 1.5)
```
If the market has 30% realized vol, the scalar is 0.6 — positions are 40% smaller than normal.

### 8.4 Drawdown Position Scaling (Continuous, Not Binary)

Instead of blocking all buys at a hard threshold, position sizes scale down gradually:

| Portfolio Drawdown | Position Size Allowed |
|---|---|
| 0% (no drawdown) | 100% |
| -5% | 90% |
| -10% | 75% |
| -15% | 50% |
| -20% | 0% (all buys blocked) |

Linear interpolation between breakpoints. A -12% drawdown gives ~65% sizing.

### 8.5 Dynamic Sector Caps

The system reads outcome patterns from the `decision_patterns` table. For sub-sectors where:
- Win rate < 40% AND
- Sample size ≥ 5 decisions

The sector cap is multiplied by `max(0.5, win_rate / 0.50)`. A sector with 30% win rate gets its cap cut to 60% of the base (e.g., 50% → 30%).

---

## 9. Signal Quality Tracker

The signal quality tracker closes the feedback loop: it measures how well each factor actually predicts returns and feeds corrections back into the weighting system.

### 9.1 Rolling Factor IC

Same concept as Section 8.2, but tracked as a **time series** instead of a single average:
- For each scoring date in the last 126 days, compute per-factor IC
- Compute 4-week rolling mean of IC values
- **Decay flag:** If recent 3-period mean < 50% of prior 3-period mean, the factor is losing predictive power

### 9.2 Hit Rate

For each past scoring run where BUY signals had time to play out (1-month forward returns available):
```
hit_rate = (number of BUY signals that outperformed SPY at 1 month) / total BUY signals
```

**Factor contribution:** Spearman correlation between each factor's score at decision time and the subsequent excess return. Shows which factors actually drove the wins and losses.

### 9.3 Factor Decay Detection

A factor is "decaying" if:
- There are ≥8 IC observations
- Prior-half average IC > 0.01 (it was once predictive)
- Current-half average IC < 50% of prior-half (it's losing power)
- Linear slope of IC over time confirms the trend

**Recommendations:** `reduce_weight` if current IC is still positive, `strongly_reduce_weight` if current IC turned negative.

### 9.4 Feedback Weights (Double Shrinkage)

The signal quality tracker computes its own recommended weights using a two-stage shrinkage:

```
Stage 1: w_stage1 = 0.5 × ic_weight + 0.5 × equal_weight     [same as IC-based]
Stage 2: w_final  = 0.7 × w_stage1  + 0.3 × production_weight [anchor to current config]
```

Decaying factors have their IC halved before Stage 1, pulling their weight down.

These feedback weights are injected into the adaptive system (Section 8), overriding the simple IC-based weights when outcome data is available.

---

## 10. Universe Management & Discovery

### 10.1 Static Universe

The base universe is `config/universe.csv` with columns:
```
ticker, name, sub_sector, market_cap_tier, risk_tier
```

~224 tickers across 11 GICS sectors with 32 sub-sectors.

### 10.2 Discovery Engine

Four sources scan for new candidates outside the universe:

1. **Finviz screens** (6 screens):
   - `large_cap_earnings_growth`: Market cap >$10B, EPS growth >5%, ROE >15%
   - `mid_cap_high_growth`: Market cap $2B-$10B, EPS growth >20%, sales growth >10%
   - `undervalued_growth`: Forward P/E <20, EPS growth >10%, PEG <1.5
   - `quality_momentum`: Perf Quarter >10%, EPS growth >5%, ROE >10%
   - `speculative_growth`: Market cap >$50M, positive sales growth, volume >100K, price >$2 — **catches risky emerging stocks like RKLB**
   - `momentum_breakout`: Quarter performance >30%, volume >200K — **no market cap requirement**

2. **SEC EDGAR:** Recent 8-K filings (material events)
3. **Yahoo Finance trending:** Most active, trending stocks
4. **Earnings beats:** Stocks that beat EPS estimates by >5% in the last 14 days

### 10.3 Risk Tier Classification

Every ticker gets a risk tier based on market cap and profitability:

| Tier | Criteria |
|------|---------|
| `standard` | Market cap ≥ $2B AND profitable (TTM EPS > 0) |
| `moderate_risk` | Market cap $500M-$2B, OR ≥$2B but unprofitable |
| `high_risk` | Market cap < $500M, OR $500M-$2B but unprofitable |

Risk profiles (Section 11) control which tiers each user can trade.

### 10.4 Auto-Promote

Candidates that appear in `factor_scores` with **decile ≥ 8 for 2 consecutive scoring runs** are automatically promoted to the universe:
1. Look up the candidate in `factor_scores` for the last 2 scoring dates
2. If both scores are decile 8+, classify its risk tier
3. Add to `universe.csv` with the computed risk_tier
4. Trigger price backfill for the new ticker

### 10.5 Auto-Demote (Flag Only)

Universe tickers that score **decile ≤ 3 for all scoring runs in the last 90 days** are flagged as `flagged_weak` in the discovery_candidates table. They are NOT automatically removed — only flagged for human review.

---

## 11. Risk Profiles

Five risk levels control how aggressively the pipeline trades:

| Level | Label | Buy Min Decile | Min Decile Change | Position Scalar | Chase Threshold | Chase Mode | Max Position | Drawdown Alert / Halt | Allowed Tiers |
|-------|-------|---------------|-------------------|----------------|----------------|------------|-------------|----------------------|--------------|
| 1 | Conservative | 9 | 3 | 0.7× | 3% | strict | 7% | -10% / -15% | standard only |
| 2 | Cautious | 9 | 3 | 0.85× | 4% | strict | 8% | -12% / -18% | standard only |
| 3 | Balanced | 8 | 2 | 1.0× | 5% | gradient | 10% | -15% / -20% | standard, moderate |
| 4 | Growth | 8 | 2 | 1.2× | 7% | allow | 12% | -20% / -25% | all tiers |
| 5 | Aggressive | 7 | 1 | 1.4× | 10% | allow | 15% | -25% / -30% | all tiers |

**Chase modes:**
- `strict`: If price is up more than the threshold in the last month, the trade is **blocked entirely**
- `gradient`: Size is linearly reduced. `multiplier = max(0, 1 - (excess / 10%))`. A stock up 10% past the threshold gets zero size.
- `allow`: No chase penalty at all

**Risk tier filtering:**
- Conservative/Cautious users only see "standard" (large, profitable) stocks
- Balanced adds "moderate_risk"
- Growth/Aggressive see all tickers including "high_risk" (small-cap, unprofitable)

---

## 12. Pipeline Execution Order

When you click "Run Pipeline" in the UI, these steps execute in sequence:

| Step | Name | What Happens |
|------|------|-------------|
| 1 | Price Ingestion | Fetch today's EOD prices from Polygon (skip if already have them) |
| 1b | Fundamentals | Refresh quarterly data from Simfin/yfinance (skip if <14 days since last) |
| 1c | Forward Estimates | Refresh analyst estimates (skip if <7 days since last) |
| 2 | Scoring | Compute all 6 factors → composite score → deciles for every ticker. **GATE: User reviews scores.** |
| 3 | Adaptive Analysis | Detect market regime, compute IC-based weights, tune constraints |
| 3b | Universe Refresh | Auto-promote high-scoring discoveries, flag weak tickers |
| 4a | Signal Generation | Apply decision rules → BUY/SELL/HOLD/TRIM/ADD for every ticker. **GATE: User reviews signals.** |
| 4b | Trade Proposals | Convert signals to concrete proposals (shares, dollar amounts, constraints). **GATE: User reviews proposals.** |
| 5 | News Research | Collect and AI-summarize news for all relevant tickers + competitive intelligence. **GATE: User reviews research.** |
| 6 | Judge Evaluation | Claude evaluates each proposal (or reviews portfolio if no proposals). **GATE: User reviews verdicts.** |
| 7 | Execution | If auto-mode enabled: execute approved trades via brokerage. If not: wait for manual approval. |
| 8 | Self-Learning | Log outcomes, compute signal quality metrics, update adaptive state |

Each gate pauses the pipeline for human review. The user can:
- Approve and continue
- Exclude tickers or modify signals
- Override deciles or share counts
- Add context notes that the judge will see
- Abort the pipeline

---

## 13. Key Configuration Parameters

All defaults are in `backend/config/settings.py`:

### Factor Weights
```
momentum_12m1m:            15%
eps_growth_yoy:            15%
revenue_growth_yoy:        15%
gross_margin_trend:        10%
relative_valuation:        20%
forward_estimate_revision: 25%
```
These are starting defaults. The adaptive system adjusts them based on measured IC.

### Position Sizing
```
max_single_position_weight: 10%
min_position_size_pct:      1%
max_cash_pct:               20%
min_positions:              8
max_positions:              25
```

### Turnover Controls
```
max_turnover_per_week_pct:  15%
min_holding_days:           20
min_decile_change_to_trade: 2
max_new_positions_per_run:  3
max_trades_per_run:         5
```

### Quality & Valuation
```
winsorize_std:              3.0
sector_neutral_blend:       1.0  (pure sector-neutral)
sector_neutral_min_group:   5
max_absolute_per:           40
max_relative_per_vs_peer:   1.5
min_quality_zscore:         -0.5
quality_recent_quarters:    4
```

### Risk Limits
```
max_portfolio_drawdown_alert: -15%
max_portfolio_drawdown_halt:  -20%
max_subsector_weight:         50% (per sub-sector)
```

### Ingestion
```
fundamentals_cooldown_days:   14
forward_estimates_cooldown:   7 days
discovery_cooldown:           24 hours
```

### Transaction Cost Assumptions
```
round_trip_cost_bps_large:    10 bps  (>$5B market cap)
round_trip_cost_bps_mid:      20 bps  (<$5B market cap)
```

### Benchmarks
```
primary_benchmark:   SPY  (broad market)
secondary_benchmark: QQQ  (tech tilt)
```

---

*Document generated from Trademark pipeline source code. All formulas and thresholds are as of the current codebase.*
