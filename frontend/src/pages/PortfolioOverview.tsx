import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useState, useEffect, useRef } from "react"
import { api } from "@/lib/api"
import type { PortfolioData, PortfolioSnapshot, QuarterlyFundamental, HoldingTime, BrokerageStatus } from "@/lib/api"
import { formatPercent, pnlColor, cn } from "@/lib/utils"
import { PageHeader } from "@/components/layout/page-header"
import { MetricCard } from "@/components/ui/metric-card"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { DataTable } from "@/components/ui/data-table"
import { Loader2, TrendingUp, BarChart3, ChevronDown, ChevronUp } from "lucide-react"
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  XAxis,
  YAxis,
  CartesianGrid,
  AreaChart,
  Area,
} from "recharts"
import { Treemap } from "@/components/charts/Treemap"
import { Waterfall } from "@/components/charts/Waterfall"
import { BubbleChart } from "@/components/charts/BubbleChart"
import { Sparkline } from "@/components/charts/Sparkline"

const tooltipStyle = {
  backgroundColor: "#0f1310",
  border: "1px solid #262d27",
  borderRadius: "6px",
  color: "#e8efe6",
  fontSize: "12px",
  fontFamily: "'JetBrains Mono', monospace",
  boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
}

const tooltipLabelStyle = { color: "#7a8479" }

interface PositionRow {
  ticker: string
  shares: number
  cost_basis: number
  current_price: number
  market_value: number
  unrealized_pnl: number
  unrealized_pct: number
  weight?: number
}

const slotCSS = `
@keyframes slot-in-up {
  from { transform: translateY(60%); opacity: 0; }
  to   { transform: translateY(0);   opacity: 1; }
}
@keyframes slot-in-down {
  from { transform: translateY(-60%); opacity: 0; }
  to   { transform: translateY(0);    opacity: 1; }
}
.slot-in-up   { animation: slot-in-up   0.38s cubic-bezier(0.22,1,0.36,1) both; }
.slot-in-down { animation: slot-in-down 0.38s cubic-bezier(0.22,1,0.36,1) both; }
`

function SlotValue({ value, dir, className }: {
  value: string
  dir: "up" | "down" | null
  className?: string
}) {
  const [prev, setPrev] = useState(value)
  const [current, setCurrent] = useState(value)

  useEffect(() => {
    if (value !== current) {
      setPrev(current)
      setCurrent(value)
    }
  }, [value]) // eslint-disable-line react-hooks/exhaustive-deps

  const animClass = dir === "up" ? "slot-in-up" : dir === "down" ? "slot-in-down" : ""

  return (
    <span className={className} style={{ display: "inline-flex", alignItems: "baseline" }}>
      {current.split("").map((char, i) => {
        const changed = char !== (prev[i] ?? "")
        const isDigit = /\d/.test(char)
        if (!changed || !isDigit || !animClass) {
          return <span key={i}>{char}</span>
        }
        const delay = `${(current.length - 1 - i) * 0.03}s`
        return (
          <span key={i} style={{ display: "inline-block", overflow: "hidden", verticalAlign: "baseline" }}>
            <span
              key={`${i}-${char}`}
              className={animClass}
              style={{ display: "inline-block", animationDelay: delay }}
            >
              {char}
            </span>
          </span>
        )
      })}
    </span>
  )
}

const flashCSS = `
@keyframes flash-up {
  0%   { box-shadow: none; }
  20%  { box-shadow: 0 0 0 2px rgba(126,231,135,0.45), 0 0 12px rgba(126,231,135,0.10); }
  100% { box-shadow: none; }
}
@keyframes flash-down {
  0%   { box-shadow: none; }
  20%  { box-shadow: 0 0 0 2px rgba(255,107,107,0.45), 0 0 12px rgba(255,107,107,0.10); }
  100% { box-shadow: none; }
}
@keyframes cell-flash-up {
  0%   { background-color: transparent; }
  25%  { background-color: rgba(126,231,135,0.18); border-radius: 4px; }
  100% { background-color: transparent; }
}
@keyframes cell-flash-down {
  0%   { background-color: transparent; }
  25%  { background-color: rgba(255,107,107,0.18); border-radius: 4px; }
  100% { background-color: transparent; }
}
.flash-card-up   { animation: flash-up   0.9s ease-out; }
.flash-card-down { animation: flash-down 0.9s ease-out; }
.flash-cell-up   { animation: cell-flash-up   0.9s ease-out; }
.flash-cell-down { animation: cell-flash-down 0.9s ease-out; }
`

function useFlash(value: number): "up" | "down" | null {
  const [dir, setDir] = useState<"up" | "down" | null>(null)
  const prev = useRef<number | null>(null)
  useEffect(() => {
    if (prev.current !== null && value !== prev.current) {
      setDir(value > prev.current ? "up" : "down")
      const t = setTimeout(() => setDir(null), 900)
      prev.current = value
      return () => clearTimeout(t)
    }
    if (prev.current === null) prev.current = value
  }, [value])
  return dir
}

function FlashCell({ value, children, className }: { value: number; children: React.ReactNode; className?: string }) {
  const dir = useFlash(value)
  return (
    <span className={cn(className, dir === "up" ? "flash-cell-up" : dir === "down" ? "flash-cell-down" : "")}>
      {children}
    </span>
  )
}

function formatSnapshotDate(dateStr: string): string {
  // Slice to "YYYY-MM-DD" first — pandas may return "2024-01-05T00:00:00.000"
  const [year, month, day] = dateStr.slice(0, 10).split("-").map(Number)
  const d = new Date(year, month - 1, day)
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

interface HistoryTooltipProps {
  active?: boolean
  payload?: Array<{ value: number; name: string; payload: Record<string, unknown> }>
  label?: string
  currency: string
}

// Values in chartData are already rate-converted, so format directly here
function fmtConverted(value: number): string {
  const abs = Math.abs(value)
  const sign = value < 0 ? "-" : ""
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`
  if (abs >= 1_000) return `${sign}$${abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  return `${sign}$${abs.toFixed(2)}`
}

function HistoryTooltip({ active, payload, label, currency }: HistoryTooltipProps) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload as unknown as PortfolioSnapshot & { displayDate: string; total_value: number; unrealized_pnl: number }
  const returnPct = (d.total_return_pct ?? 0) * 100
  return (
    <div style={{ ...tooltipStyle, padding: "10px 14px", minWidth: 190 }}>
      <p className="text-xs text-muted-foreground mb-2">{d.displayDate ?? label}</p>
      <div className="space-y-1">
        <div className="flex justify-between gap-6">
          <span className="text-xs text-muted-foreground">Portfolio Value ({currency})</span>
          <span className="text-xs font-semibold">{fmtConverted(d.total_value)}</span>
        </div>
        <div className="flex justify-between gap-6">
          <span className="text-xs text-muted-foreground">Unrealized P&L</span>
          <span className={cn("text-xs font-semibold", d.unrealized_pnl >= 0 ? "text-profit" : "text-loss")}>
            {fmtConverted(d.unrealized_pnl)}
          </span>
        </div>
        <div className="flex justify-between gap-6">
          <span className="text-xs text-muted-foreground">Total Return</span>
          <span className={cn("text-xs font-semibold", returnPct >= 0 ? "text-profit" : "text-loss")}>
            {returnPct >= 0 ? "+" : ""}{returnPct.toFixed(2)}%
          </span>
        </div>
        <div className="flex justify-between gap-6">
          <span className="text-xs text-muted-foreground">Positions</span>
          <span className="text-xs font-semibold">{d.n_positions}</span>
        </div>
      </div>
    </div>
  )
}

function PortfolioHistoryChart({ snapshots, rate, currency }: {
  snapshots: PortfolioSnapshot[]
  rate: number
  currency: string
}) {
  // Reverse so oldest → newest left-to-right
  const chartData = [...snapshots].reverse().map((s) => {
    const [year, month, day] = s.snapshot_date.slice(0, 10).split("-").map(Number)
    const d = new Date(year, month - 1, day)
    return {
      ...s,
      displayDate: d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }),
      total_value: s.total_value * rate,
      unrealized_pnl: s.unrealized_pnl * rate,
      shortDate: formatSnapshotDate(s.snapshot_date),
    }
  })

  const isEmpty = chartData.length === 0
  const minVal = isEmpty ? 0 : Math.min(...chartData.map((d) => d.total_value))
  const maxVal = isEmpty ? 0 : Math.max(...chartData.map((d) => d.total_value))
  const domain: [number, number] = isEmpty ? [0, 1] : [minVal * 0.985, maxVal * 1.015]

  const LINE_COLOR = "#c5fb45"

  const firstDate = !isEmpty ? snapshots[snapshots.length - 1].snapshot_date.slice(0, 10) : ""
  const lastDate = !isEmpty ? snapshots[0].snapshot_date.slice(0, 10) : ""

  return (
    <Card className="mb-4">
      <CardTitle
        meta={
          !isEmpty
            ? `${chartData.length} snapshot${chartData.length === 1 ? "" : "s"} · ${firstDate} → ${lastDate}`
            : undefined
        }
      >
        Portfolio History
      </CardTitle>
      <CardContent>
        {isEmpty ? (
          <div className="flex flex-col items-center justify-center h-40 gap-2 text-muted-foreground">
            <TrendingUp className="h-8 w-8 opacity-30" />
            <p className="text-sm">No history yet — run the pipeline to start tracking.</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 10 }}>
              <defs>
                <linearGradient id="historyGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={LINE_COLOR} stopOpacity={0.25} />
                  <stop offset="95%" stopColor={LINE_COLOR} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="#1d231e" strokeDasharray="3 3" />
              <XAxis
                dataKey="shortDate"
                tick={{ fontSize: 11, fill: "#7a8479" }}
                axisLine={{ stroke: "#1d231e" }}
                tickLine={false}
                interval={chartData.length <= 10 ? 0 : Math.floor(chartData.length / 8)}
                padding={{ left: 12, right: 12 }}
              />
              <YAxis
                domain={domain}
                tickFormatter={(v: number) => {
                  const abs = Math.abs(v)
                  if (abs >= 1_000_000) return `$${(abs / 1_000_000).toFixed(1)}M`
                  if (abs >= 1_000) return `$${(abs / 1_000).toFixed(1)}k`
                  return `$${abs.toFixed(0)}`
                }}
                tick={{ fontSize: 11, fill: "#7a8479", dy: -4 }}
                axisLine={false}
                tickLine={false}
                width={62}
              />
              <Tooltip
                content={<HistoryTooltip currency={currency} />}
                cursor={{ stroke: LINE_COLOR, strokeWidth: 1, strokeDasharray: "4 2" }}
              />
              <Area
                type="monotone"
                dataKey="total_value"
                stroke={LINE_COLOR}
                strokeWidth={2}
                fill="url(#historyGrad)"
                dot={(props: { cx?: number; cy?: number; index?: number; key?: React.Key | null }) => {
                  const { cx = 0, cy = 0, index = 0, key } = props
                  const isLast = index === chartData.length - 1
                  if (!isLast && chartData.length > 15) return <g key={key} />
                  return (
                    <circle
                      key={key}
                      cx={cx}
                      cy={cy}
                      r={isLast ? 4 : 2.5}
                      fill={LINE_COLOR}
                      stroke="#0f1310"
                      strokeWidth={2}
                    />
                  )
                }}
                activeDot={{ r: 5, fill: LINE_COLOR, stroke: "#111113", strokeWidth: 2 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  )
}

function formatQtr(dateStr: string): string {
  const [y, m] = dateStr.slice(0, 10).split("-").map(Number)
  const q = Math.ceil(m / 3)
  return `Q${q} ${String(y).slice(-2)}`
}

function fmtCompact(value: number): string {
  const abs = Math.abs(value)
  const sign = value < 0 ? "-" : ""
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(0)}M`
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(0)}K`
  return `${sign}$${abs.toFixed(0)}`
}

function FinancialStats({ tickers }: { tickers: string[] }) {
  const [selectedTicker, setSelectedTicker] = useState(tickers[0] ?? "")
  const [expanded, setExpanded] = useState(true)

  const { data: fundamentals, isLoading } = useQuery<QuarterlyFundamental[]>({
    queryKey: ["quarterly-fundamentals", selectedTicker],
    queryFn: () => api.getQuarterlyFundamentals(selectedTicker),
    enabled: !!selectedTicker,
    staleTime: 5 * 60 * 1000,
  })

  useEffect(() => {
    if (tickers.length > 0 && !tickers.includes(selectedTicker)) {
      setSelectedTicker(tickers[0])
    }
  }, [tickers]) // eslint-disable-line react-hooks/exhaustive-deps

  if (tickers.length === 0) return null

  const quarters = (fundamentals ?? [])
    .filter((f) => f.ticker === selectedTicker)
    .slice(-8)

  return (
    <Card className="mb-4">
      <CardTitle
        meta={`Last 8 quarters · ${selectedTicker}`}
        action={
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1 h-[24px] px-2 rounded-[4px] font-mono text-[11px] font-medium text-muted-foreground hover:text-foreground hover:bg-surface-2 transition-colors"
          >
            {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
            {expanded ? "Collapse" : "Expand"}
          </button>
        }
      >
        Financial Statistics
      </CardTitle>
      {expanded && (
        <CardContent>
          {/* Ticker selector */}
          <div className="flex flex-wrap gap-1 mb-5">
            {tickers.map((t) => (
              <button
                key={t}
                onClick={() => setSelectedTicker(t)}
                className={cn(
                  "h-[24px] px-2 rounded-[4px] font-mono text-[11px] font-medium transition-colors",
                  t === selectedTicker
                    ? "bg-primary text-background"
                    : "text-muted-foreground hover:text-foreground hover:bg-surface",
                )}
              >
                {t}
              </button>
            ))}
          </div>

          {isLoading ? (
            <div className="flex items-center justify-center h-40 gap-2 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
              <span className="text-sm">Loading financials...</span>
            </div>
          ) : quarters.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-32 gap-2 text-muted-foreground">
              <BarChart3 className="h-8 w-8 opacity-30" />
              <p className="text-sm">No quarterly data available for {selectedTicker}.</p>
              <p className="text-xs">Run fundamentals ingestion to load data.</p>
            </div>
          ) : (
            <>
              {/* Revenue + Net Income + EPS Stat Boxes */}
              {(() => {
                const latest = quarters[quarters.length - 1]
                const stats = [
                  {
                    label: "Quarterly Revenue ($B)",
                    series: quarters.map((q) => q.revenue ?? 0),
                    latest: latest?.revenue ?? null,
                    suffix: "B",
                    stroke: "#c5fb45",
                    fill: "rgba(197, 251, 69, 0.12)",
                    scale: 1e9,
                  },
                  {
                    label: "Quarterly Net Income ($B)",
                    series: quarters.map((q) => q.net_income ?? 0),
                    latest: latest?.net_income ?? null,
                    suffix: "B",
                    stroke: "#7ee787",
                    fill: "rgba(126, 231, 135, 0.12)",
                    scale: 1e9,
                  },
                  {
                    label: "Quarterly EPS ($)",
                    series: quarters.map((q) => q.eps_diluted ?? 0),
                    latest: latest?.eps_diluted ?? null,
                    suffix: "",
                    stroke: "#6cb4ee",
                    fill: "rgba(108, 180, 238, 0.12)",
                    scale: 1,
                  },
                ]
                return (
                  <div className="grid grid-cols-3 gap-4 mb-5">
                    {stats.map((s) => (
                      <div
                        key={s.label}
                        className="rounded-md border border-line bg-bg-2 px-3 py-2.5"
                      >
                        <div className="font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1">
                          {s.label}
                        </div>
                        <div className="font-mono text-[16px] font-medium tabular-nums text-foreground">
                          {s.latest != null
                            ? `$${(s.latest / s.scale).toFixed(2)}${s.suffix}`
                            : "—"}
                        </div>
                        <div className="mt-1.5">
                          <Sparkline
                            data={s.series}
                            width={220}
                            height={36}
                            stroke={s.stroke}
                            fill={s.fill}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                )
              })()}

              {/* Quarterly Financials Table */}
              <div>
                <div className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted-foreground mb-2">
                  Quarterly Financials
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full font-mono text-[11px] tabular-nums">
                    <thead>
                      <tr className="border-b border-line">
                        <th className="text-left py-2 px-2 text-[10px] uppercase tracking-[0.1em] text-muted-foreground font-semibold">Quarter</th>
                        <th className="text-right py-2 px-2 text-[10px] uppercase tracking-[0.1em] text-muted-foreground font-semibold">Revenue</th>
                        <th className="text-right py-2 px-2 text-[10px] uppercase tracking-[0.1em] text-muted-foreground font-semibold">YoY%</th>
                        <th className="text-right py-2 px-2 text-[10px] uppercase tracking-[0.1em] text-muted-foreground font-semibold">Gross Profit</th>
                        <th className="text-right py-2 px-2 text-[10px] uppercase tracking-[0.1em] text-muted-foreground font-semibold">Operating Inc</th>
                        <th className="text-right py-2 px-2 text-[10px] uppercase tracking-[0.1em] text-muted-foreground font-semibold">Net Income</th>
                        <th className="text-right py-2 px-2 text-[10px] uppercase tracking-[0.1em] text-muted-foreground font-semibold">YoY%</th>
                        <th className="text-right py-2 px-2 text-[10px] uppercase tracking-[0.1em] text-muted-foreground font-semibold">EPS</th>
                        <th className="text-right py-2 px-2 text-[10px] uppercase tracking-[0.1em] text-muted-foreground font-semibold">YoY%</th>
                      </tr>
                    </thead>
                    <tbody>
                      {quarters.map((q) => (
                        <tr key={q.fiscal_period_end} className="border-b border-line/40 hover:bg-surface-2">
                          <td className="py-1.5 px-2 font-semibold text-foreground">{formatQtr(q.fiscal_period_end)}</td>
                          <td className="text-right py-1.5 px-2 text-fg-dim">{q.revenue != null ? fmtCompact(q.revenue) : "—"}</td>
                          <td className={cn("text-right py-1.5 px-2", q.revenue_yoy != null ? (q.revenue_yoy >= 0 ? "text-profit" : "text-loss") : "text-muted-2")}>
                            {q.revenue_yoy != null ? `${q.revenue_yoy >= 0 ? "+" : ""}${(q.revenue_yoy * 100).toFixed(1)}%` : "—"}
                          </td>
                          <td className="text-right py-1.5 px-2 text-fg-dim">{q.gross_profit != null ? fmtCompact(q.gross_profit) : "—"}</td>
                          <td className="text-right py-1.5 px-2 text-fg-dim">{q.operating_income != null ? fmtCompact(q.operating_income) : "—"}</td>
                          <td className={cn("text-right py-1.5 px-2", (q.net_income ?? 0) < 0 ? "text-loss" : "text-fg-dim")}>
                            {q.net_income != null ? fmtCompact(q.net_income) : "—"}
                          </td>
                          <td className={cn("text-right py-1.5 px-2", q.net_income_yoy != null ? (q.net_income_yoy >= 0 ? "text-profit" : "text-loss") : "text-muted-2")}>
                            {q.net_income_yoy != null ? `${q.net_income_yoy >= 0 ? "+" : ""}${(q.net_income_yoy * 100).toFixed(1)}%` : "—"}
                          </td>
                          <td className="text-right py-1.5 px-2 text-fg-dim">{q.eps_diluted != null ? `$${q.eps_diluted.toFixed(2)}` : "—"}</td>
                          <td className={cn("text-right py-1.5 px-2", q.eps_diluted_yoy != null ? (q.eps_diluted_yoy >= 0 ? "text-profit" : "text-loss") : "text-muted-2")}>
                            {q.eps_diluted_yoy != null ? `${q.eps_diluted_yoy >= 0 ? "+" : ""}${(q.eps_diluted_yoy * 100).toFixed(1)}%` : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </CardContent>
      )}
    </Card>
  )
}

export default function PortfolioOverview() {
  const [currency, setCurrency] = useState<"USD" | "CAD">("CAD")
  const queryClient = useQueryClient()

  // Background sync runs on a 10s interval (silent — no toasts on transient
  // brokerage errors so we don't spam the user when the upstream is flaky).
  const syncMutation = useMutation({
    mutationFn: () => api.syncPortfolio(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["portfolio"] }),
    onError: (err) => {
      // Sync failures should surface in the console so we notice when
      // SnapTrade is unreachable. Don't toast — happens too often during
      // weekend hours to be useful.
      console.warn("Portfolio sync failed:", err)
    },
  })

  const { data, isLoading, error } = useQuery<PortfolioData>({
    queryKey: ["portfolio"],
    queryFn: api.getPortfolio,
    // Refetch every 10s independently of the sync mutation. The /api/portfolio
    // endpoint itself triggers a brokerage refresh now, so each poll returns
    // truly live data instead of stale React-Query cache.
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
  })

  const { data: rateData } = useQuery({
    queryKey: ["exchange-rate"],
    queryFn: () => api.getExchangeRate("USD", "CAD"),
    staleTime: 5 * 60 * 1000,
  })

  const { data: historyData } = useQuery<PortfolioSnapshot[]>({
    queryKey: ["portfolio-history"],
    queryFn: () => api.getPortfolioHistory(180),
    staleTime: 60 * 1000,
  })

  const { data: holdingTimes } = useQuery<HoldingTime[]>({
    queryKey: ["holding-times"],
    queryFn: api.getHoldingTimes,
    staleTime: 60 * 1000,
  })

  const { data: brokerageStatus } = useQuery<BrokerageStatus>({
    queryKey: ["brokerage-status"],
    queryFn: api.getBrokerageStatus,
    staleTime: 60 * 1000,
  })
  const brokerageConnected = brokerageStatus?.connected ?? false
  const holdMap = new Map((holdingTimes ?? []).map((h) => [h.ticker, h]))

  // No explicit auto-sync useEffect any more: the `["portfolio"]` query's
  // refetchInterval polls /api/portfolio every 10s, and the backend
  // endpoint now refreshes from SnapTrade as part of that call. The
  // syncMutation above stays available for the manual "Sync now" button
  // and any other explicit triggers.

  const rate = currency === "CAD" ? (rateData?.rate ?? 1.38) : 1

  const portfolioFlash = useFlash(data?.pnl?.total_portfolio_value ?? 0)
  const unrealizedFlash = useFlash(data?.pnl?.total_unrealized_pnl ?? 0)
  const cashFlash = useFlash(data?.pnl?.cash ?? 0)

  function fmt(value: number): string {
    const converted = value * rate
    const abs = Math.abs(converted)
    const sign = converted < 0 ? "-" : ""
    if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`
    if (abs >= 1_000) return `${sign}$${abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    return `${sign}$${abs.toFixed(2)}`
  }

  const toggleActions = (
    <div className="flex overflow-hidden rounded-[4px] border border-line-2">
      <button
        onClick={() => setCurrency("USD")}
        className={cn(
          "h-[28px] px-3 font-mono text-[12px] font-medium transition-colors border-r border-line-2",
          currency === "USD"
            ? "bg-primary/8 text-primary"
            : "text-muted-foreground hover:text-foreground",
        )}
      >
        USD
      </button>
      <button
        onClick={() => setCurrency("CAD")}
        className={cn(
          "h-[28px] px-3 font-mono text-[12px] font-medium transition-colors",
          currency === "CAD"
            ? "bg-primary/8 text-primary"
            : "text-muted-foreground hover:text-foreground",
        )}
      >
        CAD
      </button>
    </div>
  )

  const portfolioTitle = "Portfolio"
  const portfolioPrefix = brokerageConnected ? (
    <img
      src="/brokerages/wealthsimple_logo.jpg"
      alt="Wealthsimple"
      className="h-6 w-6 rounded-sm object-cover"
    />
  ) : undefined

  if (isLoading) {
    return (
      <>
        <PageHeader title={portfolioTitle} prefix={portfolioPrefix} actions={toggleActions} />
        <div className="grid grid-cols-4 gap-3 mb-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-28 rounded-xl border border-border/60 bg-card animate-shimmer" />
          ))}
        </div>
        <div className="grid grid-cols-2 gap-6">
          {[0, 1].map((i) => (
            <div key={i} className="h-64 rounded-xl border border-border/60 bg-card animate-shimmer" />
          ))}
        </div>
      </>
    )
  }

  if (error || !data) {
    return (
      <PageHeader
        title="Portfolio"
        description="Failed to load portfolio data. Is the backend running on port 8000?"
        actions={toggleActions}
      />
    )
  }

  const { pnl, weights } = data
  const positions: PositionRow[] = (pnl.positions || []).sort(
    (a, b) => b.market_value - a.market_value,
  )

  // Today's return — compare the most recent snapshot to the prior one.
  // historyData is ordered newest → oldest, so [0] is today and [1] is the
  // previous trading session. Both values are pre-rate-conversion (USD).
  const todayReturn: { dollar: number; pct: number } | null = (() => {
    if (!historyData || historyData.length < 2) return null
    const today = historyData[0].total_value
    const prev = historyData[1].total_value
    if (prev <= 0) return null
    return { dollar: today - prev, pct: (today - prev) / prev }
  })()

  // Allocation pie — cohesive OKLCH palette: tickers get green→teal→blue hues at
  // consistent lightness/chroma; cash gets a muted gray so it visually recedes.
  const tickerEntries = Object.entries(weights)
  const cashWeight = Math.max(0, 1 - tickerEntries.reduce((a, [, v]) => a + v, 0))
  const pieData = [
    ...tickerEntries.map(([name, value], i) => ({
      name,
      value,
      color: `oklch(${0.62 + (i % 3) * 0.06} 0.16 ${130 + i * 22})`,
    })),
    { name: "Cash", value: cashWeight, color: "#525a52" },
  ].filter((d) => d.value > 0.001)

  const columns = [
    {
      key: "ticker",
      header: "Ticker",
      render: (r: PositionRow) => <span className="font-semibold">{r.ticker}</span>,
    },
    {
      key: "shares",
      header: "Shares",
      align: "right" as const,
      render: (r: PositionRow) => <span>{r.shares}</span>,
    },
    {
      key: "price",
      header: "Price",
      align: "right" as const,
      render: (r: PositionRow) => (
        <FlashCell value={r.current_price}>
          <SlotValue value={fmt(r.current_price)} dir={null} />
        </FlashCell>
      ),
    },
    {
      key: "mktval",
      header: "Market Value",
      align: "right" as const,
      render: (r: PositionRow) => (
        <FlashCell value={r.market_value}>
          <SlotValue value={fmt(r.market_value)} dir={null} />
        </FlashCell>
      ),
    },
    {
      key: "pnl",
      header: "P&L",
      align: "right" as const,
      render: (r: PositionRow) => {
        const sign = r.unrealized_pnl >= 0 ? "+" : ""
        return (
          <FlashCell value={r.unrealized_pnl} className={cn("font-medium", pnlColor(r.unrealized_pnl))}>
            <SlotValue value={`${sign}${fmt(r.unrealized_pnl)}`} dir={r.unrealized_pnl >= 0 ? "up" : "down"} />
          </FlashCell>
        )
      },
    },
    {
      key: "pnlpct",
      header: "P&L %",
      align: "right" as const,
      render: (r: PositionRow) => {
        const sign = r.unrealized_pct >= 0 ? "+" : ""
        return (
          <span className={cn("font-medium tabular-nums", pnlColor(r.unrealized_pct))}>
            {sign}{(r.unrealized_pct * 100).toFixed(2)}%
          </span>
        )
      },
    },
    {
      key: "weight",
      header: "Weight",
      align: "right" as const,
      render: (r: PositionRow) => (
        <span className="text-muted-foreground">
          {weights[r.ticker] ? formatPercent(weights[r.ticker]) : "-"}
        </span>
      ),
    },
    {
      key: "hold",
      header: "Hold Status",
      align: "right" as const,
      render: (r: PositionRow) => {
        const h = holdMap.get(r.ticker)
        if (!h) return <span className="text-muted-foreground/50">—</span>
        // Bar fills as |P&L %| approaches the tradeable threshold. Floor at
        // 6% so a freshly protected position still shows a visible sliver.
        const rawPct = h.hold_progress ?? 0
        const pct = Math.max(rawPct, 0.06)
        const statusColor =
          h.hold_status === "protected" ? "text-amber-400" :
          h.hold_status === "maturing" ? "text-primary" :
          "text-profit"
        const statusLabel =
          h.hold_status === "protected" ? "PROTECTED" :
          h.hold_status === "maturing" ? "MATURING" :
          "TRADEABLE"
        const pnlPct = h.hold_pnl_pct ?? 0
        const thresholdPct = h.hold_tradeable_threshold_pct ?? 0.05
        const pnlLabel = `${pnlPct >= 0 ? "+" : ""}${(pnlPct * 100).toFixed(2)}%`
        const tooltip = `P&L ${pnlLabel} · tradeable at ±${(thresholdPct * 100).toFixed(0)}%`
        return (
          <div className="flex items-center gap-2.5 justify-end" title={tooltip}>
            <div className="h-1.5 w-[80px] shrink-0 rounded-full bg-line-2 overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full transition-all",
                  h.hold_status === "protected" ? "bg-amber-400" :
                  h.hold_status === "maturing" ? "bg-primary" :
                  "bg-profit",
                )}
                style={{ width: `${pct * 100}%` }}
              />
            </div>
            <span className={cn("font-mono text-[10px] font-semibold tracking-[0.06em] w-[64px] text-left", statusColor)}>
              {statusLabel}
            </span>
          </div>
        )
      },
    },
  ]

  return (
    <>
      <style>{slotCSS + flashCSS}</style>
      <PageHeader title={portfolioTitle} prefix={portfolioPrefix} actions={toggleActions} />

      {/* Metric Cards */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        <MetricCard
          accent
          label={`Portfolio Value (${currency})`}
          value={fmt(pnl.total_portfolio_value)}
          valueNode={<SlotValue value={fmt(pnl.total_portfolio_value)} dir={portfolioFlash} />}
          delta={formatPercent(pnl.total_return_pct)}
          deltaValue={pnl.total_return_pct}
          sparkline={
            (historyData?.length ?? 0) > 1 ? (
              <Sparkline
                data={[...(historyData ?? [])].reverse().slice(-30).map((s) => s.total_value * rate)}
                width={70}
                height={20}
              />
            ) : undefined
          }
          className={portfolioFlash === "up" ? "flash-card-up" : portfolioFlash === "down" ? "flash-card-down" : ""}
        />
        <MetricCard
          label="Unrealized P&L"
          value={fmt(pnl.total_unrealized_pnl)}
          valueNode={<SlotValue value={fmt(pnl.total_unrealized_pnl)} dir={unrealizedFlash} />}
          delta={`${formatPercent(pnl.total_return_pct)} return`}
          deltaValue={pnl.total_unrealized_pnl}
          className={unrealizedFlash === "up" ? "flash-card-up" : unrealizedFlash === "down" ? "flash-card-down" : ""}
        />
        <MetricCard
          label="Cash"
          value={fmt(pnl.cash)}
          valueNode={<SlotValue value={fmt(pnl.cash)} dir={cashFlash} />}
          sub={
            pnl.total_portfolio_value > 0
              ? `${((pnl.cash / pnl.total_portfolio_value) * 100).toFixed(1)}% of portfolio`
              : undefined
          }
          className={cashFlash === "up" ? "flash-card-up" : cashFlash === "down" ? "flash-card-down" : ""}
        />
        <MetricCard
          label="Today's Return"
          value={todayReturn ? `${todayReturn.dollar >= 0 ? "+" : ""}${fmt(todayReturn.dollar)}` : "—"}
          delta={todayReturn ? formatPercent(todayReturn.pct) : undefined}
          deltaValue={todayReturn?.dollar}
          sub={todayReturn ? "vs prior snapshot" : "needs 2+ snapshots"}
        />
      </div>

      {/* Portfolio History */}
      <PortfolioHistoryChart snapshots={historyData ?? []} rate={rate} currency={currency} />

      {/* Current Holdings — full width */}
      <Card className="mb-4">
        <CardTitle meta={positions.length > 0 ? `${positions.length} position${positions.length === 1 ? "" : "s"}` : undefined}>
          Current Holdings
        </CardTitle>
        <CardContent>
          <DataTable
            columns={columns}
            data={positions}
            rowKey={(r) => r.ticker}
            emptyMessage="No positions. Update portfolio_state.json with your holdings."
          />
        </CardContent>
      </Card>

      {/* Position Heatmap (Treemap) + Allocation */}
      {positions.length > 0 && (
        <div className="grid gap-4 mb-4" style={{ gridTemplateColumns: "1.6fr 1fr" }}>
          <Card>
            <CardTitle meta="Sized by market value · Colored by return">
              Position Heatmap
            </CardTitle>
            <CardContent>
              <Treemap
                data={positions}
                width={680}
                height={340}
                accessor={(p) => p.market_value}
                colorAccessor={(p) => p.unrealized_pct * 100}
                formatValue={(v) => `$${(v / 1000).toFixed(1)}k`}
                formatLabel={(p) => p.ticker}
              />
              <div className="flex items-center justify-between mt-3 font-mono text-[10px] tracking-[0.08em] text-muted-foreground">
                <span>RETURN %</span>
                <div className="flex items-center gap-2 flex-1 mx-4">
                  <span className="text-loss">−15%</span>
                  <div
                    className="flex-1 h-1.5 rounded-[1px]"
                    style={{
                      background:
                        "linear-gradient(90deg, oklch(0.65 0.22 25), oklch(0.55 0.05 142), oklch(0.80 0.22 142))",
                    }}
                  />
                  <span className="text-profit">+15%</span>
                </div>
                <span>{positions.length} POSITIONS</span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardTitle meta="Including cash">Allocation</CardTitle>
            <CardContent>
              {pieData.length > 0 ? (
                <>
                  <div className="relative">
                    <ResponsiveContainer width="100%" height={200}>
                      <PieChart>
                        <Pie
                          data={pieData}
                          cx="50%"
                          cy="50%"
                          innerRadius={55}
                          outerRadius={85}
                          dataKey="value"
                          nameKey="name"
                          stroke="none"
                          paddingAngle={2}
                        >
                          {pieData.map((d) => (
                            <Cell key={d.name} fill={d.color} />
                          ))}
                        </Pie>
                        <Tooltip
                          formatter={(value) => formatPercent(Number(value))}
                          contentStyle={tooltipStyle}
                          labelStyle={tooltipLabelStyle}
                          itemStyle={{ color: "#fafafa" }}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                      <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-muted-foreground">
                        Total
                      </span>
                      <span className="font-mono text-[14px] font-medium tabular-nums text-foreground mt-0.5">
                        {fmt(pnl.total_portfolio_value)}
                      </span>
                    </div>
                  </div>
                  <div className="mt-2 pt-2.5 border-t border-line space-y-1 font-mono text-[11px]">
                    {pieData.map((d) => (
                      <div key={d.name} className="flex items-center gap-2 py-[3px]">
                        <span
                          className="inline-block h-[9px] w-[9px] rounded-[2px]"
                          style={{ backgroundColor: d.color }}
                        />
                        <span className="flex-1 text-fg-dim">{d.name}</span>
                        <span className="tabular-nums text-foreground min-w-[40px] text-right">
                          {(d.value * 100).toFixed(1)}%
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">No allocation data</p>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* P&L Attribution (Waterfall) */}
      {positions.length > 0 && (
        <Card className="mb-4">
          <CardTitle meta="Per-position contribution to unrealized P&L">
            P&L Attribution
          </CardTitle>
          <CardContent>
            <Waterfall
              data={[...positions]
                .sort((a, b) => b.unrealized_pnl - a.unrealized_pnl)
                .map((p) => ({
                  label: p.ticker,
                  value: Math.round(p.unrealized_pnl * rate),
                }))}
              width={1100}
              height={260}
              formatValue={(v) => (v >= 0 ? "$" : "-$") + Math.abs(v).toLocaleString()}
            />
          </CardContent>
        </Card>
      )}

      {/* Risk / Return Profile (BubbleChart) */}
      {positions.length > 1 && (
        <Card className="mb-4">
          <CardTitle meta="Each circle = one position · X: return % · Y: capital deployed · Size: market value">
            Risk / Return Profile
          </CardTitle>
          <CardContent>
            <BubbleChart
              data={positions.map((p) => ({
                ticker: p.ticker,
                return_pct: p.unrealized_pct * 100,
                cost_basis: (p.market_value - p.unrealized_pnl) * rate,
                market_value: p.market_value * rate,
                pnl: p.unrealized_pnl,
              }))}
              width={1100}
              height={320}
              x={(d) => d.return_pct}
              y={(d) => d.cost_basis}
              size={(d) => d.market_value}
              label={(d) => d.ticker}
              color={(d) => (d.pnl >= 0 ? "#7ee787" : "#ff6b6b")}
              formatX={(v) => `${v.toFixed(1)}%`}
              formatY={(v) => {
                const abs = Math.abs(v)
                if (abs >= 1_000_000) return `$${(abs / 1_000_000).toFixed(1)}M`
                if (abs >= 1_000) return `$${(abs / 1_000).toFixed(1)}k`
                return `$${abs.toFixed(0)}`
              }}
              xLabel="RETURN %"
              yLabel="CAPITAL DEPLOYED"
            />
          </CardContent>
        </Card>
      )}

      {/* Financial Statistics */}
      {positions.length > 0 && (
        <FinancialStats tickers={positions.map((p) => p.ticker)} />
      )}
    </>
  )
}
