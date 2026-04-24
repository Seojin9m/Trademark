import { useState, useCallback, useRef, useEffect } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { StockMetricsGrid } from "@/lib/api"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { MetricCard } from "@/components/ui/metric-card"
import { cn } from "@/lib/utils"
import { useToast } from "@/contexts/toast-context"
import {
  RefreshCw, Check, X, Edit2, RotateCcw, Shield,
  ArrowUp, ArrowDown, ArrowUpDown, Pencil, Database,
} from "lucide-react"

const METRIC_LABELS: Record<string, string> = {
  eps_growth_yoy: "EPS Growth YoY",
  revenue_growth_yoy: "Rev Growth YoY",
  gross_margin_trend: "Margin Trend",
  momentum_12m1m: "Momentum 12M-1M",
  relative_valuation: "Rel Valuation",
  quality_score: "Quality Score",
  per_ratio: "P/E Ratio",
  per_vs_peer: "P/E vs Peer",
  recent_price_change: "Recent Price Chg",
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
  return value.toFixed(3)
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-sm rounded-xl border border-border/60 bg-card p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2.5">
            <div className="flex items-center justify-center h-9 w-9 rounded-lg bg-primary/15">
              <Pencil className="h-4 w-4 text-primary" />
            </div>
            <div>
              <p className="text-sm font-semibold">{ticker}</p>
              <p className="text-xs text-muted-foreground">{METRIC_LABELS[metric] || metric}</p>
            </div>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>

        {hint && (
          <p className="text-[11px] text-muted-foreground/60 mb-4 ml-[46px]">{hint.description}</p>
        )}

        {/* Current values */}
        <div className="grid grid-cols-2 gap-3 mb-4">
          <div className="rounded-lg bg-muted/40 border border-border/40 px-3 py-2">
            <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-0.5">
              <Database className="inline h-2.5 w-2.5 mr-0.5 -mt-px" />
              Computed
            </p>
            <p className="text-sm font-mono font-medium">
              {formatMetricValue(metric, rawValue)}
            </p>
          </div>
          <div className={cn(
            "rounded-lg border px-3 py-2",
            hasOverride
              ? "bg-blue-500/10 border-blue-500/30"
              : "bg-muted/40 border-border/40",
          )}>
            <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-0.5">
              <Edit2 className="inline h-2.5 w-2.5 mr-0.5 -mt-px" />
              Override
            </p>
            <p className={cn("text-sm font-mono font-medium", hasOverride ? "text-blue-400" : "text-muted-foreground")}>
              {hasOverride ? formatMetricValue(metric, userValue) : "None"}
            </p>
          </div>
        </div>

        {/* Input */}
        <div className="mb-4">
          <label className="block text-xs font-medium text-muted-foreground mb-1.5">
            New value {isPct && <span className="text-muted-foreground/50">(%)</span>}
          </label>
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
            className="w-full rounded-lg border border-border bg-background px-3 py-2.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50"
            autoFocus
          />
          {isPct && (
            <p className="text-[10px] text-muted-foreground/50 mt-1">
              Enter as percentage (e.g. 25 for 25%). Stored as decimal (0.25).
            </p>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          {hasOverride && (
            <Button
              variant="outline"
              size="sm"
              onClick={onClear}
              className="shrink-0 border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
            >
              <RotateCcw className="h-3 w-3 mr-1.5" />
              Reset
            </Button>
          )}
          <div className="flex-1" />
          <Button variant="outline" size="sm" onClick={onClose} className="shrink-0">
            Cancel
          </Button>
          <Button size="sm" onClick={handleSave} disabled={saving || !inputVal} className="shrink-0">
            {saving ? <RefreshCw className="h-3 w-3 mr-1.5 animate-spin" /> : <Check className="h-3 w-3 mr-1.5" />}
            Save
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

  return (
    <div className="space-y-5">
      <PageHeader
        title="Stock Data Grid"
        description="View and correct numeric factor data. User-corrected values override computed values for scoring."
        actions={
          <div className="flex items-center gap-2">
            {overrideCount > 0 && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  if (confirm(`Reset all ${overrideCount} user override(s) to computed values?`)) {
                    resetAllMutation.mutate()
                  }
                }}
                disabled={resetAllMutation.isPending}
                className="border-loss/40 text-loss hover:bg-loss/10"
              >
                <RotateCcw className={cn("mr-1.5 h-3.5 w-3.5", resetAllMutation.isPending && "animate-spin")} />
                Reset All Edits ({overrideCount})
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={() => ingestMutation.mutate()}
              disabled={ingestMutation.isPending}
            >
              <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", ingestMutation.isPending && "animate-spin")} />
              Refresh Fundamentals
            </Button>
          </div>
        }
      />

      {/* Fundamentals status */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <MetricCard label="Data As Of" value={grid?.as_of_date || "—"} />
        <MetricCard label="Tickers" value={String(grid?.tickers.length || 0)} />
        <MetricCard label="Last Fundamentals" value={fundStatus?.last_ingested_at?.slice(0, 10) || "Never"} />
        <MetricCard label="Fundamentals Status" value={fundStatus?.should_ingest ? "Refresh needed" : "Up to date"} />
      </div>

      {/* Search + Legend */}
      <Card>
        <CardContent className="p-4 space-y-3">
          <input
            type="text"
            placeholder="Search ticker..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          />
          <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <div className="h-3 w-3 rounded bg-blue-500/20 border border-blue-500/30" />
              <span>User-corrected value</span>
            </div>
            <div className="flex items-center gap-1.5">
              <Pencil className="h-3 w-3" />
              <span>Click any cell to edit</span>
            </div>
            <div className="flex items-center gap-1.5">
              <Badge variant="profit">Good</Badge>
              <span>Passes quality filter</span>
            </div>
            <div className="flex items-center gap-1.5">
              <Badge variant="loss">Fail</Badge>
              <span>Below quality threshold</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Data grid */}
      {metricsLoading ? (
        <Card><CardContent className="p-8 text-center text-muted-foreground">Loading metrics...</CardContent></Card>
      ) : !grid || filteredTickers.length === 0 ? (
        <Card><CardContent className="p-8 text-center text-muted-foreground">No metrics data. Run the pipeline first.</CardContent></Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border bg-muted/30">
                    <th
                      className="sticky left-0 bg-muted/30 px-3 py-2 text-left font-medium text-muted-foreground z-10 cursor-pointer select-none hover:text-foreground transition-colors"
                      onClick={() => toggleSort("ticker")}
                    >
                      <span className="inline-flex items-center gap-1">
                        Ticker
                        {sortCol === "ticker" ? (sortDir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />) : <ArrowUpDown className="h-3 w-3 opacity-30" />}
                      </span>
                    </th>
                    <th
                      className="px-3 py-2 text-center font-medium text-muted-foreground cursor-pointer select-none hover:text-foreground transition-colors"
                      onClick={() => toggleSort("quality")}
                    >
                      <span className="inline-flex items-center gap-1">
                        Quality
                        {sortCol === "quality" ? (sortDir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />) : <ArrowUpDown className="h-3 w-3 opacity-30" />}
                      </span>
                    </th>
                    {metrics.map((m) => (
                      <th
                        key={m}
                        className="px-3 py-2 text-right font-medium text-muted-foreground whitespace-nowrap cursor-pointer select-none hover:text-foreground transition-colors"
                        onClick={() => toggleSort(m)}
                      >
                        <span className="inline-flex items-center justify-end gap-1">
                          {METRIC_LABELS[m] || m}
                          {sortCol === m ? (sortDir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />) : <ArrowUpDown className="h-3 w-3 opacity-30" />}
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
                      <tr key={ticker} className="border-b border-border/50 hover:bg-muted/20 transition-colors group">
                        <td className="sticky left-0 bg-background px-3 py-2 font-mono font-medium z-10">
                          {ticker}
                        </td>
                        <td className="px-3 py-2 text-center">
                          {qa ? (
                            <Badge variant={qa.is_good_stock ? "profit" : "loss"}>
                              {qa.is_good_stock ? (
                                <><Shield className="mr-0.5 h-3 w-3" />Good</>
                              ) : (
                                <>Fail</>
                              )}
                            </Badge>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        {metrics.map((metric) => {
                          const cell = tickerData[metric]
                          const hasOverride = cell?.user_value !== null && cell?.user_value !== undefined

                          return (
                            <td
                              key={metric}
                              className={cn(
                                "px-3 py-2 text-right font-mono cursor-pointer transition-colors",
                                hasOverride && "bg-blue-500/10",
                                "hover:bg-primary/5",
                              )}
                              onClick={() => setEditingCell({ ticker, metric })}
                            >
                              <div className="flex items-center justify-end gap-1.5">
                                <span className={cn(
                                  cell?.effective_value !== null && cell?.effective_value !== undefined
                                    ? (cell.effective_value > 0 ? "text-green-400" : cell.effective_value < 0 ? "text-red-400" : "")
                                    : "text-muted-foreground"
                                )}>
                                  {formatMetricValue(metric, cell?.effective_value ?? null)}
                                </span>
                                {hasOverride && (
                                  <Edit2 className="h-2.5 w-2.5 text-blue-400 shrink-0" />
                                )}
                              </div>
                            </td>
                          )
                        })}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

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
    </div>
  )
}
