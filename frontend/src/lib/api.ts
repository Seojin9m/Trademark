import { apiFetch } from "./utils"

export interface Position {
  ticker: string
  shares: number
  cost_basis: number
  current_price: number
  market_value: number
  unrealized_pnl: number
  unrealized_pct: number
  weight?: number
}

export interface PnL {
  total_portfolio_value: number
  total_unrealized_pnl: number
  total_return_pct: number
  cash: number
  positions: Position[]
}

export interface PortfolioData {
  portfolio: { positions: Array<{ ticker: string; shares: number; cost_basis: number }>, cash: number }
  pnl: PnL
  weights: Record<string, number>
  portfolio_value: number
}

export interface FactorScore {
  ticker: string
  date: string
  composite_score: number
  score_decile: number
  momentum_12m1m: number | null
  eps_growth_yoy: number | null
  revenue_growth_yoy: number | null
  gross_margin_trend: number | null
  relative_valuation: number | null
}

export interface Proposal {
  proposal_id: string
  run_id: string | null
  created_at: string
  ticker: string
  action: string
  shares: number
  status: string
  signal_data: string | Record<string, unknown>
  constraint_check: string | Record<string, unknown>
  judge_response: string | Record<string, unknown> | null
  human_decision: string | null
  human_notes: string | null
  reason: string | null
}

export interface JudgeLogEntry {
  log_id: string
  created_at: string
  proposal_id: string
  ticker: string
  action: string
  verdict: string
  confidence: number
  model_used: string
}

export interface RiskMetrics {
  portfolio_value: number
  total_return_pct: number
  unrealized_pnl: number
  cash_pct: number
  n_positions: number
  sector_weights: Record<string, number>
  drawdown_alert_level: number
  drawdown_halt_level: number
}

export interface BinaryEvent {
  event_type: string
  expected_date: string | null
  description: string
  potential_impact: string
}

export interface NewsResearchItem {
  ticker: string
  research_date: string
  headlines: string[]
  ai_summary: string
  sentiment: string
  binary_events: BinaryEvent[]
  risk_factors: string[]
  opportunities: string[]
  data_sources: string[]
  confidence: number
}

export interface DecisionOutcome {
  proposal_id: string
  ticker: string
  action: string
  decision_date: string
  entry_price: number | null
  shares: number | null
  composite_score: number | null
  score_decile: number | null
  prior_decile: number | null
  judge_verdict: string | null
  judge_confidence: number | null
  sector: string | null
  sub_sector: string | null
  proposal_status: string | null
  return_1w: number | null
  return_1m: number | null
  return_3m: number | null
  excess_return_1w: number | null
  excess_return_1m: number | null
  excess_return_3m: number | null
  outcome_1m: string | null
}

export interface OutcomeSummary {
  total_decisions: number
  classified: number
  pending_measurement: number
  good: number
  bad: number
  neutral: number
  win_rate: number | null
  avg_excess_return_1m: number | null
  avg_excess_return_3m: number | null
  approved_win_rate: number | null
  approved_total: number
  rejected_win_rate: number | null
  rejected_total: number
}

export interface DecisionPattern {
  pattern_id: string
  dimension: string
  dimension_value: string
  sample_size: number
  win_rate: number | null
  avg_excess_return_1m: number | null
  avg_excess_return_3m: number | null
  best_ticker: string | null
  worst_ticker: string | null
  is_alert: boolean
  alert_message: string | null
}

export interface AdaptiveState {
  min_decile_change: number
  position_size_scalar: number
  max_new_positions_per_run: number
  max_trades_per_run: number
  drawdown_schedule: Array<{ drawdown: number; size_pct: number }>
  recommended_factor_weights: Record<string, number>
  regime: {
    vol_regime: string
    realized_vol: number
    momentum_regime: string
    momentum_21d: number
    score_dispersion: number
  }
  rationale: string[]
  computed_at: string
}

export interface BrokerageAccount {
  id: string
  name: string
  number: string
  institution: string
  account_type?: string
  status?: string
  sync_status: string
  last_sync?: string
  balance?: number
  currency?: string
}

export interface BrokerageStatus {
  connected: boolean
  status: string
  accounts: BrokerageAccount[]
  user_id?: string
}

export interface PipelineRun {
  run_id: string
}

export interface PipelineEvent {
  step: string
  status: string
  message: string
  summary?: Record<string, unknown>
  gate_data?: Record<string, unknown>
  gate_name?: string
}

export interface AnalystPositionReview {
  ticker: string
  stance: "add" | "hold" | "trim" | "exit"
  reasoning: string
  conviction: number
}

export interface AnalystReview {
  review_id: string
  created_at: string
  portfolio_value: number
  overall_stance: "bullish" | "neutral" | "bearish"
  summary: string
  market_context: string
  portfolio_health_score: number
  position_reviews: AnalystPositionReview[]
  strengths: string[]
  concerns: string[]
  opportunities: string[]
  risk_factors: string[]
  pipeline_guidance: string[]
  apply_to_pipeline: boolean
}

export interface PortfolioSnapshot {
  snapshot_date: string
  total_value: number
  cash: number
  positions_value: number
  n_positions: number
  unrealized_pnl: number
  total_return_pct: number
  benchmark_value: number | null
}

export interface StockMetricValue {
  raw_value: number | null
  user_value: number | null
  effective_value: number | null
}

export interface StockMetricsGrid {
  as_of_date: string | null
  tickers: string[]
  metrics: string[]
  grid: Record<string, Record<string, StockMetricValue>>
}

export interface FundamentalsStatus {
  should_ingest: boolean
  reason: string
  last_ingested_at: string | null
  record_count: number
  notes: string | null
}

export interface QualityAssessment {
  ticker: string
  date: string
  is_good_stock: boolean
  quality_score: number
  quality_reasons: string
  per_ratio: number | null
  per_vs_peer: number | null
  per_absolute_pass: boolean
  per_relative_pass: boolean
  price_opportunity_score: number
}

export interface QuarterlyFundamental {
  ticker: string
  fiscal_period_end: string
  report_date: string
  revenue: number | null
  gross_profit: number | null
  operating_income: number | null
  net_income: number | null
  eps_diluted: number | null
  revenue_yoy: number | null
  net_income_yoy: number | null
  eps_diluted_yoy: number | null
  gross_profit_yoy: number | null
  operating_income_yoy: number | null
}





export interface HoldingTime {
  ticker: string
  buy_date: string | null
  days_held: number | null
  min_hold_days: number
  recommended_hold_days: number
  hold_status: "protected" | "maturing" | "tradeable" | "unknown"
  // Hold-status now derives from |P&L %| magnitude rather than holding time.
  // hold_progress is 0..1 (how close to "tradeable" the position is).
  hold_pnl_pct?: number
  hold_progress?: number
  hold_tradeable_threshold_pct?: number
  is_good_stock: boolean
  score_decile: number
}

// Watchlist + sectors + single-ticker analysis types (introduced on main).
// PipelineControl.tsx and Watchlist.tsx import these names directly.
export interface WatchlistItem {
  ticker: string
  company_name: string | null
  sub_sector: string | null
  added_at: string | null
  notes: string | null
  priority: number
  composite_score?: number | null
  score_decile?: number | null
  quality_score?: number | null
}

export interface SectorInfo {
  sub_sector: string
  ticker_count: number
  tickers: string[]
}

export interface TickerAnalysis {
  ticker: string
  recommendation?: string
  confidence?: number
  reasoning?: string
  factors?: Record<string, unknown>
  // The endpoint returns a structured payload from analyze_single_ticker; the
  // exact shape is data-driven, so callers should treat this as a loose blob.
  [key: string]: unknown
}

export interface PipelineRunParams {
  // Reserved for future per-run knobs (date override, dry-run, etc).
  // Currently the backend just accepts an empty POST body.
  as_of_date?: string
  dry_run?: boolean
}

export const api = {
  getPortfolio: () => apiFetch<PortfolioData>("/portfolio"),

  // Watchlist
  getWatchlist: () => apiFetch<WatchlistItem[]>("/watchlist"),
  addToWatchlist: (ticker: string, notes = "", priority = 1) =>
    apiFetch<{ status: string }>("/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker, notes, priority }),
    }),
  removeFromWatchlist: (ticker: string) =>
    apiFetch<{ status: string }>(`/watchlist/${encodeURIComponent(ticker)}`, {
      method: "DELETE",
    }),

  // Universe sectors (used by PipelineControl's per-sector status view)
  getSectors: () => apiFetch<SectorInfo[]>("/universe/sectors"),

  // Single-ticker AI analysis
  analyzeTicker: (ticker: string, risk_level = 3) =>
    apiFetch<TickerAnalysis>("/analyze/ticker", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker, risk_level }),
    }),

  getScores: (limit = 100) => apiFetch<FactorScore[]>(`/scores?limit=${limit}`),
  getProposals: (status?: string, limit = 50) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (status) params.set("status", status)
    return apiFetch<Proposal[]>(`/proposals?${params}`)
  },
  approveProposal: (id: string, notes = "") =>
    apiFetch<{ status: string }>(`/proposals/${id}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes }),
    }),
  rejectProposal: (id: string, notes = "") =>
    apiFetch<{ status: string }>(`/proposals/${id}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes }),
    }),
  deleteRun: (runId: string) =>
    apiFetch<{ status: string; deleted_count: number }>(`/proposals/run/${runId}`, { method: "DELETE" }),
  getJudgeLog: (limit = 50) => apiFetch<JudgeLogEntry[]>(`/judge-log?limit=${limit}`),
  getRisk: () => apiFetch<RiskMetrics>("/risk"),
  getExchangeRate: (from = "USD", to = "CAD") =>
    apiFetch<{ from: string; to: string; rate: number }>(`/exchange-rate?from_currency=${from}&to_currency=${to}`),
  getUniverse: () => apiFetch<Record<string, unknown>[]>("/universe"),
  getResearch: (ticker?: string, limit = 20) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (ticker) params.set("ticker", ticker)
    return apiFetch<NewsResearchItem[]>(`/research?${params}`)
  },
  triggerPipeline: () =>
    apiFetch<PipelineRun>("/pipeline/run", { method: "POST" }),
  getLearningOutcomes: (limit = 100) =>
    apiFetch<DecisionOutcome[]>(`/learning/outcomes?limit=${limit}`),
  getLearningSummary: () =>
    apiFetch<OutcomeSummary>("/learning/summary"),
  getLearningPatterns: () =>
    apiFetch<DecisionPattern[]>("/learning/patterns"),
  getLearningAlerts: () =>
    apiFetch<DecisionPattern[]>("/learning/alerts"),
  getAdaptiveState: () =>
    apiFetch<AdaptiveState>("/learning/adaptive"),
  getAutoMode: () =>
    apiFetch<{ enabled: boolean }>("/auto-mode"),
  setAutoMode: (enabled: boolean) =>
    apiFetch<{ enabled: boolean }>(`/auto-mode?enabled=${enabled}`, { method: "POST" }),
  getReviewMode: () =>
    apiFetch<{ enabled: boolean }>("/review-mode"),
  setReviewMode: (enabled: boolean) =>
    apiFetch<{ enabled: boolean }>(`/review-mode?enabled=${enabled}`, { method: "POST" }),
  getPipelineGate: (runId: string) =>
    apiFetch<{ gate_name: string | null; data?: Record<string, unknown>; created_at?: string }>(`/pipeline/gate?run_id=${runId}`),
  respondToGate: (runId: string, gateName: string, action: string, overrides?: Record<string, unknown>) =>
    apiFetch<{ status: string; gate_name: string; action: string }>("/pipeline/gate/respond", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId, gate_name: gateName, action, overrides: overrides ?? {} }),
    }),
  resetTradingData: (keepPrices = true) =>
    apiFetch<{ status: string; cleared: string[]; kept_prices: boolean }>(
      `/reset?keep_prices=${keepPrices}`,
      { method: "POST" },
    ),
  getBrokerageStatus: () =>
    apiFetch<BrokerageStatus>("/brokerage/status"),
  connectBrokerage: (broker = "WEALTHSIMPLETRADE") =>
    apiFetch<{ url: string; broker: string }>(`/brokerage/connect?broker=${broker}`, { method: "POST" }),
  syncPortfolio: (accountId?: string) =>
    apiFetch<{ status: string; positions: number; cash: number; currency: string }>(
      `/brokerage/sync${accountId ? `?account_id=${accountId}` : ""}`,
      { method: "POST" },
    ),
  disconnectBrokerage: () =>
    apiFetch<{ status: string }>("/brokerage/disconnect", { method: "POST" }),
  getPortfolioHistory: (days = 90) =>
    apiFetch<PortfolioSnapshot[]>(`/portfolio/history?days=${days}`),
  getHoldingTimes: () =>
    apiFetch<HoldingTime[]>("/portfolio/holding-times"),
  getUserNotes: () =>
    apiFetch<{ text: string; images: { name: string; data: string; mime: string }[]; updated_at: string | null }>("/user-notes"),
  setUserNotes: (text: string, images: { name: string; data: string; mime: string }[] = []) =>
    apiFetch<{ text: string; images: { name: string; data: string; mime: string }[]; updated_at: string | null }>("/user-notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, images }),
    }),
  clearUserNotes: () =>
    apiFetch<{ text: string; images: { name: string; data: string; mime: string }[]; updated_at: string | null }>("/user-notes", {
      method: "DELETE",
    }),
  requestAnalystReview: () =>
    apiFetch<AnalystReview>("/analyst/review", { method: "POST" }),
  getAnalystReview: () =>
    apiFetch<{ review: AnalystReview | null }>("/analyst/review"),
  applyAnalystReview: (apply: boolean) =>
    apiFetch<{ apply_to_pipeline: boolean; review_id: string }>(
      `/analyst/apply?apply=${apply}`, { method: "POST" }
    ),
  getStockMetrics: () =>
    apiFetch<StockMetricsGrid>("/stock-metrics"),
  updateStockMetric: (ticker: string, metricName: string, userValue: number) =>
    apiFetch<{ status: string; ticker: string; metric: string; user_value: number }>(
      `/stock-metrics/${ticker}/${metricName}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_value: userValue }),
      }
    ),
  clearStockMetricOverride: (ticker: string, metricName: string) =>
    apiFetch<{ status: string; ticker: string; metric: string }>(
      `/stock-metrics/${ticker}/${metricName}`,
      { method: "DELETE" }
    ),
  clearAllStockMetricOverrides: () =>
    apiFetch<{ status: string; overrides_removed: number }>(
      "/stock-metrics",
      { method: "DELETE" }
    ),
  getFundamentalsStatus: () =>
    apiFetch<FundamentalsStatus>("/fundamentals/status"),
  triggerFundamentalsIngest: () =>
    apiFetch<{ status: string; message: string }>("/fundamentals/ingest", { method: "POST" }),
  getQualityAssessments: () =>
    apiFetch<QualityAssessment[]>("/quality-assessments"),
  getQuarterlyFundamentals: (ticker?: string) => {
    const params = ticker ? `?ticker=${ticker}` : ""
    return apiFetch<QuarterlyFundamental[]>(`/fundamentals/quarterly${params}`)
  },
}
