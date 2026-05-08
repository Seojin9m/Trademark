import { useState, useCallback, useRef, useEffect } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { StockMetricsGrid } from "@/lib/api"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { MetricCard } from "@/components/ui/metric-card"
import { cn } from "@/lib/utils"
import { useToast } from "@/contexts/toast-context"
import {
  RefreshCw, Check, X, RotateCcw, Shield,
  ArrowUp, ArrowDown, ArrowUpDown,
} from "lucide-react"

const METRIC_LABELS: Record<string, string> = {
  eps_growth_yoy: "EPS Growth",
  revenue_growth_yoy: "Rev Growth",
  gross_margin_trend: "Margin Trend",
  momentum_12m1m: "Momentum",
  relative_valuation: "Rel Valuation",
  quality_score: "Quality Score",
  per_ratio: "P/E Ratio",
  per_vs_peer: "P/E vs Peers",
  recent_price_change: "Recent Δ%",
  price_dip_score: "Dip Score",
}

const METRIC_HINTS: Record<string, { description: string; format: "pct" | "ratio" | "zscore" }> = {
  eps_growth_yoy: { description: "Year-over-year earnings per share growth rate", format: "pct" },
  revenue_growth_yoy: { description: "Year-over-year revenue growth rate", format: "pct" },
  gross_margin_trend: { description: "Change in gross margin over recent quarters", format: "zscore" },
  momentum_12m1m: { description: "12-month return excluding most recent month", format: "pct" },
  relative_valuation: { description: "Price-to-sales vs sector peers (higher = cheaper)", format: "zscore" },
  quality_score: { description: "Composite quality z-score from fundamentals", format: "zscore" },
  per_ratio: { description: "Price-to-earnings ratio (TTM)", format: "ratio" },
  per_vs_peer: { description: "P/E ratio relative to sector median (1.0 = at median)", format: "ratio" },
  recent_price_change: { description: "Price change over the last month", format: "pct" },
  price_dip_score: { description: "Inverted recent price change (positive = dipped)", format: "zscore" },
}

function formatMetricValue(metric: string, value: number | null): string {
  if (value === null || value === undefined) return "—"
  const hint = METRIC_HINTS[metric]
  if (hint?.format === "ratio") return value.toFixed(1)
  if (hint?.format === "pct") return `${(value * 100).toFixed(1)}%`
  return value.toFixed(2)
}

// Heat-color a cell by directional magnitude. The data grid mixes formats:
// pct values run -1..+1 (decimal), z-scores run roughly -3..+3, ratios are
// non-diverging. We use a sqrt curve so mid-range values get most of the
// alpha budget — a linear ramp leaves the typical 0.3-0.7σ range nearly
// invisible since most of its budget gets eaten by the extreme tail.
function heatBg(metric: string, value: number | null): string {
  if (value === null || value === undefined) return "transparent"
  const hint = METRIC_HINTS[metric]
  if (hint?.format === "ratio") return "transparent"

  // Magnitude threshold below which we render neutral (avoids tinting noise).
  const NEUTRAL_THRESHOLD = hint?.format === "pct" ? 0.005 : 0.1
  if (Math.abs(value) < NEUTRAL_THRESHOLD) return "transparent"

  // Cap: pct at 50%, z-score at 2σ. sqrt curve below pulls saturation up
  // for mid-range values.
  const cap = hint?.format === "pct" ? 0.5 : 2.0
  const ratio = Math.min(1, Math.abs(value) / cap)
  const intensity = Math.sqrt(ratio)

  // Alpha 0.10..0.50 — strong values get full saturation, neutrals fade out.
  const alpha = 0.10 + intensity * 0.40
  if (value > 0) return `rgba(126, 231, 135, ${alpha})`
  return `rgba(255, 107, 107, ${alpha})`
}

// ─── Edit Metric Panel ──────────────────────────────────────────────────────

interface EditPanelProps {
  ticker: string
  metric: string
  rawValue: number | null
  userValue: number | null
  onSave: (value: number) => void
  onClear: () => void
  onClose: () => void
  saving: boolean
}

function EditMetricPanel({ ticker, metric, rawValue, userValue, onSave, onClear, onClose, saving }: EditPanelProps) {
  const hint = METRIC_HINTS[metric]
  const isPct = hint?.format === "pct"
  const hasOverride = userValue !== null && userValue !== undefined

  const displayToInput = (v: number | null) => {
    if (v === null || v === undefined) return ""
    return isPct ? (v * 100).toFixed(2) : v.toFixed(4)
  }

  const [inputVal, setInputVal] = useState(displayToInput(userValue ?? rawValue))
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.select()
  }, [])

  const handleSave = () => {
    const parsed = parseFloat(inputVal)
    if (isNaN(parsed)) return
    onSave(isPct ? parsed / 100 : parsed)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-[380px] rounded-md border border-line-2 bg-surface p-5"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header row */}
        <div className="flex items-center mb-3.5">
          <span className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
            Override: {ticker} · {METRIC_LABELS[metric] || metric}
          </span>
          <span className="flex-1" />
          <button
            onClick={onClose}
            className="flex items-center justify-center h-[24px] w-[24px] rounded-[4px] text-muted-foreground hover:bg-surface-2 hover:text-foreground transition-colors"
          >
            <X className="h-3 w-3" />
          </button>
        </div>

        {hint && (
          <p className="font-mono text-[11px] text-muted-2 mb-3.5 leading-[1.5]">
            {hint.description}
          </p>
        )}

        {/* Computed | Override */}
        <div className="grid grid-cols-2 gap-3 mb-3.5">
          <div>
            <div className="font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
              Computed Value
            </div>
            <div className="font-mono text-[18px] font-medium text-foreground tabular-nums">
              {formatMetricValue(metric, rawValue)}
            </div>
          </div>
          <div>
            <div className="font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
              Current Override
            </div>
            <div className={cn(
              "font-mono text-[18px] font-medium tabular-nums",
              hasOverride ? "text-primary" : "text-muted-2",
            )}>
              {hasOverride ? formatMetricValue(metric, userValue) : "—"}
            </div>
          </div>
        </div>

        {/* New override input */}
        <div className="font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
          New Override {isPct && <span className="text-muted-2 normal-case tracking-normal">(enter as %)</span>}
        </div>
        <input
          ref={inputRef}
          type="number"
          step="any"
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSave()
            if (e.key === "Escape") onClose()
          }}
          placeholder={isPct ? "e.g. 15.5 for 15.5%" : "Enter value"}
          className="w-full h-[34px] rounded-[4px] border border-line-2 bg-bg-2 px-3 font-mono text-[13px] text-foreground tabular-nums focus:outline-none focus:border-primary/50 mb-3.5"
          autoFocus
        />

        {/* Actions */}
        <div className="flex items-center gap-1.5">
          <Button size="sm" variant="primary" onClick={handleSave} disabled={saving || !inputVal}>
            {saving ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
            Save Override
          </Button>
          {hasOverride && (
            <Button size="sm" variant="default" onClick={onClear}>
              <RotateCcw className="h-3 w-3" />
              Clear Override
            </Button>
          )}
          <span className="flex-1" />
          <Button size="sm" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  )
}

// ─── Main Grid ──────────────────────────────────────────────────────────────

export default function StockDataGrid() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [editingCell, setEditingCell] = useState<{ ticker: string; metric: string } | null>(null)
  const [search, setSearch] = useState("")
  const [sortCol, setSortCol] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")

  const toggleSort = useCallback((col: string) => {
    if (sortCol === col) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"))
    } else {
      setSortCol(col)
      setSortDir("desc")
    }
  }, [sortCol])

  const { data: metricsData, isLoading: metricsLoading } = useQuery({
    queryKey: ["stock-metrics"],
    queryFn: api.getStockMetrics,
    refetchInterval: 60_000,
  })

  const { data: fundStatus } = useQuery({
    queryKey: ["fundamentals-status"],
    queryFn: api.getFundamentalsStatus,
  })

  const { data: qualityData } = useQuery({
    queryKey: ["quality-assessments"],
    queryFn: api.getQualityAssessments,
  })

  const updateMutation = useMutation({
    mutationFn: ({ ticker, metric, value }: { ticker: string; metric: string; value: number }) =>
      api.updateStockMetric(ticker, metric, value),
    onSuccess: (_, vars) => {
      queryClient.invalidateQueries({ queryKey: ["stock-metrics"] })
      toast("success", `Updated ${vars.ticker} ${METRIC_LABELS[vars.metric] || vars.metric}`)
      setEditingCell(null)
    },
    onError: (err: Error) => {
      toast("error", "Update failed", err.message)
    },
  })

  const clearMutation = useMutation({
    mutationFn: ({ ticker, metric }: { ticker: string; metric: string }) =>
      api.clearStockMetricOverride(ticker, metric),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stock-metrics"] })
      toast("success", "Override cleared")
      setEditingCell(null)
    },
  })

  const ingestMutation = useMutation({
    mutationFn: api.triggerFundamentalsIngest,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["fundamentals-status"] })
      toast("success", "Fundamentals refresh completed")
    },
    onError: (err: Error) => {
      toast("error", "Ingest failed", err.message)
    },
  })

  const resetAllMutation = useMutation({
    mutationFn: api.clearAllStockMetricOverrides,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["stock-metrics"] })
      toast("success", `Reset ${data.overrides_removed} override(s)`)
    },
    onError: (err: Error) => {
      toast("error", "Reset failed", err.message)
    },
  })

  const qualityMap = new Map(
    (qualityData || []).map((q) => [q.ticker, q])
  )

  const grid = metricsData as StockMetricsGrid | undefined
  const metrics = grid?.metrics || []

  const overrideCount = grid
    ? Object.values(grid.grid).reduce(
        (sum, tickerMetrics) =>
          sum + Object.values(tickerMetrics).filter((v) => v.user_value != null).length,
        0,
      )
    : 0

  const filteredTickers = (() => {
    let tickers = (grid?.tickers || []).filter(
      (t) => !search || t.toLowerCase().includes(search.toLowerCase())
    )
    if (sortCol && grid) {
      tickers = [...tickers].sort((a, b) => {
        let va: number | null = null
        let vb: number | null = null

        if (sortCol === "ticker") {
          return sortDir === "asc" ? a.localeCompare(b) : b.localeCompare(a)
        }
        if (sortCol === "quality") {
          const qa = qualityMap.get(a)
          const qb = qualityMap.get(b)
          va = qa ? (qa.is_good_stock ? 1 : 0) : null
          vb = qb ? (qb.is_good_stock ? 1 : 0) : null
        } else {
          va = grid.grid[a]?.[sortCol]?.effective_value ?? null
          vb = grid.grid[b]?.[sortCol]?.effective_value ?? null
        }

        if (va === null && vb === null) return 0
        if (va === null) return 1
        if (vb === null) return -1
        return sortDir === "asc" ? va - vb : vb - va
      })
    }
    return tickers
  })()

  const editCell = editingCell && grid ? grid.grid[editingCell.ticker]?.[editingCell.metric] : null

  const sortIcon = (col: string) => {
    if (sortCol !== col) return <ArrowUpDown className="h-3 w-3 opacity-30" />
    return sortDir === "asc" ? <ArrowUp className="h-3 w-3 text-primary" /> : <ArrowDown className="h-3 w-3 text-primary" />
  }

  return (
    <>
      <PageHeader
        title="Data Grid"
        description="View and override fundamental metrics for all tracked stocks"
        actions={
          <div className="flex items-center gap-2">
            {overrideCount > 0 && (
              <Button
                size="sm"
                variant="default"
                onClick={() => {
                  if (confirm(`Reset all ${overrideCount} user override(s) to computed values?`)) {
                    resetAllMutation.mutate()
                  }
                }}
                disabled={resetAllMutation.isPending}
                className="border-loss/40 text-loss hover:bg-loss/10"
              >
                <RotateCcw className={cn("h-3 w-3", resetAllMutation.isPending && "animate-spin")} />
                Reset All ({overrideCount})
              </Button>
            )}
            <Button
              size="sm"
              variant="primary"
              onClick={() => ingestMutation.mutate()}
              disabled={ingestMutation.isPending}
            >
              <RefreshCw className={cn("h-3 w-3", ingestMutation.isPending && "animate-spin")} />
              Refresh Fundamentals
            </Button>
          </div>
        }
      />

      {/* Status metrics */}
      <div className="grid grid-cols-4 gap-4 mb-[18px]">
        <MetricCard
          accent
          label="Tickers"
          value={String(grid?.tickers.length || 0)}
          sub={`${metrics.length} metric${metrics.length === 1 ? "" : "s"}`}
        />
        <MetricCard
          label="Data As Of"
          value={grid?.as_of_date || "—"}
        />
        <MetricCard
          label="Last Fundamentals"
          value={fundStatus?.last_ingested_at?.slice(0, 10) || "Never"}
          sub={fundStatus?.should_ingest ? "Refresh needed" : "Up to date"}
        />
        <MetricCard
          label="Active Overrides"
          value={String(overrideCount)}
          sub={overrideCount === 0 ? "no edits" : "user-corrected cells"}
        />
      </div>

      {/* Grid card */}
      <Card>
        <CardTitle
          meta="Click any cell to override · cells colored by z-score"
          action={
            <input
              type="text"
              placeholder="Search ticker..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-[24px] w-[180px] rounded-[4px] border border-line-2 bg-bg-2 px-2 font-mono text-[11px] text-foreground placeholder:text-muted-2 focus:outline-none focus:border-primary/50"
            />
          }
        >
          {grid ? `${filteredTickers.length} stocks` : "Stocks"}
        </CardTitle>

        {metricsLoading ? (
          <div className="p-8 text-center text-muted-foreground">Loading metrics...</div>
        ) : !grid || filteredTickers.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground">
            {search ? `No tickers match "${search}".` : "No metrics data. Run the pipeline first."}
          </div>
        ) : (
          <div className="overflow-auto" style={{ maxHeight: 720 }}>
            <table className="w-full font-mono text-[11.5px] tabular-nums">
              <thead>
                <tr>
                  <th
                    className="sticky left-0 top-0 z-20 border-b border-line bg-bg-2 px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground cursor-pointer select-none hover:text-foreground transition-colors"
                    onClick={() => toggleSort("ticker")}
                    style={{ width: 80 }}
                  >
                    <span className="inline-flex items-center gap-1">
                      Ticker {sortIcon("ticker")}
                    </span>
                  </th>
                  <th
                    className="sticky top-0 z-10 border-b border-line bg-bg-2 px-3 py-2.5 text-center text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground cursor-pointer select-none hover:text-foreground transition-colors"
                    onClick={() => toggleSort("quality")}
                  >
                    <span className="inline-flex items-center gap-1">
                      Quality {sortIcon("quality")}
                    </span>
                  </th>
                  {metrics.map((m) => (
                    <th
                      key={m}
                      className="sticky top-0 z-10 border-b border-line bg-bg-2 px-3 py-2.5 text-right text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground whitespace-nowrap cursor-pointer select-none hover:text-foreground transition-colors"
                      onClick={() => toggleSort(m)}
                    >
                      <span className="inline-flex items-center justify-end gap-1">
                        {METRIC_LABELS[m] || m} {sortIcon(m)}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredTickers.map((ticker) => {
                  const qa = qualityMap.get(ticker)
                  const tickerData = grid.grid[ticker] || {}
                  return (
                    <tr key={ticker} className="border-b border-line/40 hover:bg-surface-2 transition-colors">
                      <td className="sticky left-0 bg-surface px-3 py-1.5 font-semibold text-foreground z-[1]">
                        {ticker}
                      </td>
                      <td className="px-3 py-1.5 text-center">
                        {qa ? (
                          <Badge variant={qa.is_good_stock ? "profit" : "loss"}>
                            {qa.is_good_stock ? (
                              <><Shield className="h-2.5 w-2.5" />Good</>
                            ) : (
                              "Fail"
                            )}
                          </Badge>
                        ) : (
                          <span className="text-muted-2">—</span>
                        )}
                      </td>
                      {metrics.map((metric) => {
                        const cell = tickerData[metric]
                        const hasOverride = cell?.user_value !== null && cell?.user_value !== undefined
                        const value = cell?.effective_value ?? null
                        return (
                          <td
                            key={metric}
                            className="relative px-3 py-1.5 text-right cursor-pointer hover:!bg-primary/10 transition-colors border-l border-line/40"
                            style={{ background: heatBg(metric, value) }}
                            onClick={() => setEditingCell({ ticker, metric })}
                          >
                            <span className={cn(value === null && "text-muted-2")}>
                              {formatMetricValue(metric, value)}
                            </span>
                            {hasOverride && (
                              <span className="absolute top-1 right-1 h-[5px] w-[5px] rounded-full bg-primary" />
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Edit modal */}
      {editingCell && grid && (
        <EditMetricPanel
          ticker={editingCell.ticker}
          metric={editingCell.metric}
          rawValue={editCell?.raw_value ?? null}
          userValue={editCell?.user_value ?? null}
          saving={updateMutation.isPending}
          onSave={(value) =>
            updateMutation.mutate({ ticker: editingCell.ticker, metric: editingCell.metric, value })
          }
          onClear={() =>
            clearMutation.mutate({ ticker: editingCell.ticker, metric: editingCell.metric })
          }
          onClose={() => setEditingCell(null)}
        />
      )}
    </>
  )
}
