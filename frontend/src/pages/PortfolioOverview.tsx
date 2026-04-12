import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useState, useEffect, useRef } from "react"
import { useToast } from "@/contexts/toast-context"
import { api } from "@/lib/api"
import type { PortfolioData, PortfolioSnapshot } from "@/lib/api"
import { formatPercent, pnlColor, cn } from "@/lib/utils"
import { PageHeader } from "@/components/layout/page-header"
import { MetricCard } from "@/components/ui/metric-card"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { DataTable } from "@/components/ui/data-table"
import { Badge } from "@/components/ui/badge"
import { RefreshCw, Loader2, TrendingUp } from "lucide-react"
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ReferenceLine,
  CartesianGrid,
  AreaChart,
  Area,
} from "recharts"

const COLORS = [
  "#6366f1", "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b",
  "#f43f5e", "#ec4899", "#3b82f6", "#14b8a6", "#f97316",
  "#84cc16", "#a855f7", "#0ea5e9", "#22d3ee", "#e879f9",
]

const tooltipStyle = {
  backgroundColor: "#111113",
  border: "1px solid #1f1f2e",
  borderRadius: "0.75rem",
  color: "#fafafa",
  fontSize: "12px",
  boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
}

const tooltipLabelStyle = { color: "#a1a1aa" }

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
  20%  { box-shadow: 0 0 0 2px rgba(34,197,94,0.55), 0 0 16px rgba(34,197,94,0.15); }
  100% { box-shadow: none; }
}
@keyframes flash-down {
  0%   { box-shadow: none; }
  20%  { box-shadow: 0 0 0 2px rgba(239,68,68,0.55), 0 0 16px rgba(239,68,68,0.15); }
  100% { box-shadow: none; }
}
@keyframes cell-flash-up {
  0%   { background-color: transparent; }
  25%  { background-color: rgba(34,197,94,0.22); border-radius: 4px; }
  100% { background-color: transparent; }
}
@keyframes cell-flash-down {
  0%   { background-color: transparent; }
  25%  { background-color: rgba(239,68,68,0.22); border-radius: 4px; }
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
  payload?: Array<{ value: number; name: string; payload: Record<string, number | string> }>
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
  const d = payload[0].payload as PortfolioSnapshot & { displayDate: string; total_value: number; unrealized_pnl: number }
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

  const LINE_COLOR = "#22c55e"  // always green

  return (
    <Card className="mb-4">
      <CardTitle>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-primary" />
            Portfolio History
          </div>
          {!isEmpty && (
            <span className="text-xs font-normal text-muted-foreground">
              {chartData.length} pipeline run{chartData.length !== 1 ? "s" : ""} · last {formatSnapshotDate(snapshots[0].snapshot_date)}
            </span>
          )}
        </div>
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
              <CartesianGrid vertical={false} stroke="#1f1f2e" strokeDasharray="3 3" />
              <XAxis
                dataKey="shortDate"
                tick={{ fontSize: 11, fill: "#71717a" }}
                axisLine={{ stroke: "#27272a" }}
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
                tick={{ fontSize: 11, fill: "#71717a", dy: -4 }}
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
                dot={(props: { cx?: number; cy?: number; index?: number; key?: string }) => {
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
                      stroke="#111113"
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

export default function PortfolioOverview() {
  const [currency, setCurrency] = useState<"USD" | "CAD">("CAD")
  const queryClient = useQueryClient()

  const { toast } = useToast()

  const syncMutation = useMutation({
    mutationFn: api.syncPortfolio,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["portfolio"] }),
    onError: (e: Error) => toast("error", "Sync Failed", e.message.replace(/^Error:\s*/, "")),
  })

  const { data, isLoading, error } = useQuery<PortfolioData>({
    queryKey: ["portfolio"],
    queryFn: api.getPortfolio,
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
    <div className="flex items-center gap-2">
      <button
        onClick={() => syncMutation.mutate()}
        disabled={syncMutation.isPending}
        className="flex items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/20 transition-colors disabled:opacity-50"
      >
        {syncMutation.isPending
          ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
          : <RefreshCw className="h-3.5 w-3.5" />}
        Sync
      </button>
      <div className="flex items-center rounded-lg border border-border/60 bg-card overflow-hidden text-sm">
      <button
        onClick={() => setCurrency("USD")}
        className={cn(
          "px-3 py-1.5 font-medium transition-colors",
          currency === "USD"
            ? "bg-primary text-primary-foreground"
            : "text-muted-foreground hover:text-foreground",
        )}
      >
        USD
      </button>
      <button
        onClick={() => setCurrency("CAD")}
        className={cn(
          "px-3 py-1.5 font-medium transition-colors",
          currency === "CAD"
            ? "bg-primary text-primary-foreground"
            : "text-muted-foreground hover:text-foreground",
        )}
      >
        CAD
      </button>
    </div>
    </div>
  )

  if (isLoading) {
    return (
      <>
        <PageHeader title="Portfolio Overview" actions={toggleActions} />
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
        title="Portfolio Overview"
        description="Failed to load portfolio data. Is the backend running on port 8000?"
        actions={toggleActions}
      />
    )
  }

  const { pnl, weights } = data
  const positions: PositionRow[] = (pnl.positions || []).sort(
    (a, b) => b.market_value - a.market_value,
  )

  // Chart data: P&L by position (keep green/red for P&L)
  const pnlChartData = positions.map((p) => ({
    ticker: p.ticker,
    pnl: p.unrealized_pnl * rate,
    fill: p.unrealized_pnl >= 0 ? "#22c55e" : "#ef4444",
  }))

  // Chart data: Return % by position (keep green/red)
  const returnChartData = positions.map((p) => ({
    ticker: p.ticker,
    return_pct: +(p.unrealized_pct * 100).toFixed(2),
    fill: p.unrealized_pct >= 0 ? "#22c55e" : "#ef4444",
  }))

  // Chart data: single market value bar per position, colored by P&L
  const valueChartData = positions.map((p) => ({
    ticker: p.ticker,
    value: p.market_value * rate,
    fill: p.unrealized_pnl >= 0 ? "#22c55e" : "#ef4444",
  }))

  // Allocation pie
  const cashWeight = Math.max(0, 1 - Object.values(weights).reduce((a, b) => a + b, 0))
  const pieData = [
    ...Object.entries(weights).map(([name, value]) => ({ name, value })),
    { name: "Cash", value: cashWeight },
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
      header: "Mkt Value",
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
      render: (r: PositionRow) => (
        <FlashCell value={r.unrealized_pnl} className={cn("font-medium", pnlColor(r.unrealized_pnl))}>
          <SlotValue value={fmt(r.unrealized_pnl)} dir={r.unrealized_pnl >= 0 ? "up" : "down"} />
        </FlashCell>
      ),
    },
    {
      key: "pnlpct",
      header: "P&L %",
      align: "right" as const,
      render: (r: PositionRow) => (
        <Badge variant={r.unrealized_pct > 0 ? "profit" : r.unrealized_pct < 0 ? "loss" : "muted"}>
          {formatPercent(r.unrealized_pct)}
        </Badge>
      ),
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
  ]

  return (
    <>
      <style>{slotCSS + flashCSS}</style>
      <PageHeader title="Portfolio Overview" actions={toggleActions} />

      {/* Metric Cards */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        <MetricCard
          label={`Portfolio Value (${currency})`}
          value={fmt(pnl.total_portfolio_value)}
          valueNode={<SlotValue value={fmt(pnl.total_portfolio_value)} dir={portfolioFlash} />}
          className={portfolioFlash === "up" ? "flash-card-up" : portfolioFlash === "down" ? "flash-card-down" : ""}
        />
        <MetricCard
          label="Unrealized P&L"
          value={fmt(pnl.total_unrealized_pnl)}
          valueNode={<SlotValue value={fmt(pnl.total_unrealized_pnl)} dir={unrealizedFlash} />}
          delta={formatPercent(pnl.total_return_pct)}
          deltaValue={pnl.total_return_pct}
          className={unrealizedFlash === "up" ? "flash-card-up" : unrealizedFlash === "down" ? "flash-card-down" : ""}
        />
        <MetricCard
          label="Cash"
          value={fmt(pnl.cash)}
          valueNode={<SlotValue value={fmt(pnl.cash)} dir={cashFlash} />}
          className={cashFlash === "up" ? "flash-card-up" : cashFlash === "down" ? "flash-card-down" : ""}
        />
        <MetricCard label="Positions" value={String(positions.length)} />
      </div>

      {/* P&L Bar Chart + Return % Chart */}
      {positions.length > 0 && (
        <div className="grid grid-cols-2 gap-4 mb-4">
          <Card>
            <CardTitle>P&L by Position</CardTitle>
            <CardContent>
              <ResponsiveContainer width="100%" height={Math.max(160, pnlChartData.length * 36)}>
                <BarChart data={pnlChartData} layout="vertical" margin={{ left: 10, right: 20 }}>
                  <CartesianGrid horizontal={false} stroke="#1f1f2e" strokeDasharray="3 3" />
                  <XAxis
                    type="number"
                    tickFormatter={(v: number) =>
                      v >= 0 ? `$${v.toLocaleString()}` : `-$${Math.abs(v).toLocaleString()}`
                    }
                    tick={{ fontSize: 11, fill: "#71717a" }}
                    axisLine={{ stroke: "#27272a" }}
                    tickLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="ticker"
                    width={50}
                    interval={0}
                    tick={{ fontSize: 12, fill: "#a1a1aa", fontWeight: 600 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    formatter={(value: number) => [fmt(value / rate), "P&L"]}
                    contentStyle={tooltipStyle}
                    labelStyle={tooltipLabelStyle}
                    itemStyle={{ color: "#fafafa" }}
                    cursor={{ fill: "rgba(99, 102, 241, 0.08)" }}
                  />
                  <ReferenceLine x={0} stroke="#3f3f46" />
                  <Bar dataKey="pnl" radius={[0, 4, 4, 0]} maxBarSize={28}>
                    {pnlChartData.map((entry, i) => (
                      <Cell key={i} fill={entry.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <Card>
            <CardTitle>Return % by Position</CardTitle>
            <CardContent>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={returnChartData} margin={{ top: 10, right: 10, bottom: 0, left: 0 }}>
                  <CartesianGrid vertical={false} stroke="#1f1f2e" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="ticker"
                    tick={{ fontSize: 12, fill: "#a1a1aa", fontWeight: 600 }}
                    axisLine={{ stroke: "#27272a" }}
                    tickLine={false}
                  />
                  <YAxis
                    tickFormatter={(v: number) => `${v}%`}
                    tick={{ fontSize: 11, fill: "#71717a" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    formatter={(value: number) => [`${value.toFixed(2)}%`, "Return"]}
                    contentStyle={tooltipStyle}
                    labelStyle={tooltipLabelStyle}
                    itemStyle={{ color: "#fafafa" }}
                    cursor={{ fill: "rgba(99, 102, 241, 0.08)" }}
                  />
                  <ReferenceLine y={0} stroke="#3f3f46" />
                  <Bar dataKey="return_pct" radius={[4, 4, 0, 0]} maxBarSize={40}>
                    {returnChartData.map((entry, i) => (
                      <Cell key={i} fill={entry.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Current Holdings — full width */}
      <Card className="mb-4">
        <CardTitle>Current Holdings</CardTitle>
        <CardContent>
          <DataTable
            columns={columns}
            data={positions}
            rowKey={(r) => r.ticker}
            emptyMessage="No positions. Update portfolio_state.json with your holdings."
          />
        </CardContent>
      </Card>

      {/* Portfolio History */}
      <PortfolioHistoryChart snapshots={historyData ?? []} rate={rate} currency={currency} />

      {/* Value Breakdown + Allocation */}
      <div className="grid grid-cols-3 gap-4 mb-4">
        {positions.length > 0 && (
          <Card className="col-span-2">
            <CardTitle>Position Value Breakdown</CardTitle>
            <CardContent>
              <ResponsiveContainer width="100%" height={Math.max(160, valueChartData.length * 36)}>
                <BarChart data={valueChartData} layout="vertical" margin={{ left: 10, right: 20 }}>
                  <CartesianGrid horizontal={false} stroke="#1f1f2e" strokeDasharray="3 3" />
                  <XAxis
                    type="number"
                    tickFormatter={(v: number) => `$${(v / 1000).toFixed(1)}k`}
                    tick={{ fontSize: 11, fill: "#71717a" }}
                    axisLine={{ stroke: "#27272a" }}
                    tickLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="ticker"
                    width={50}
                    interval={0}
                    tick={{ fontSize: 12, fill: "#a1a1aa", fontWeight: 600 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    formatter={(value: number) => [fmt(value / rate), "Market Value"]}
                    contentStyle={tooltipStyle}
                    labelStyle={tooltipLabelStyle}
                    itemStyle={{ color: "#fafafa" }}
                    cursor={{ fill: "rgba(99, 102, 241, 0.08)" }}
                  />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={20}>
                    {valueChartData.map((entry, i) => (
                      <Cell key={i} fill={entry.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardTitle>Allocation</CardTitle>
          <CardContent>
            {pieData.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={180}>
                  <PieChart>
                    <Pie
                      data={pieData}
                      cx="50%"
                      cy="50%"
                      innerRadius={45}
                      outerRadius={75}
                      dataKey="value"
                      nameKey="name"
                      stroke="none"
                      paddingAngle={2}
                    >
                      {pieData.map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
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
                <div className="mt-2 space-y-1.5">
                  {pieData.map((d, i) => (
                    <div key={d.name} className="flex items-center justify-between text-sm">
                      <div className="flex items-center gap-2.5">
                        <span
                          className="inline-block h-2.5 w-2.5 rounded-full"
                          style={{ backgroundColor: COLORS[i % COLORS.length] }}
                        />
                        <span className="text-muted-foreground">{d.name}</span>
                      </div>
                      <span className="font-medium">{formatPercent(d.value)}</span>
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
    </>
  )
}
