import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useState, useEffect, useRef } from "react"
import { useToast } from "@/contexts/toast-context"
import { api } from "@/lib/api"
import type { PortfolioData } from "@/lib/api"
import { formatPercent, pnlColor, cn } from "@/lib/utils"
import { PageHeader } from "@/components/layout/page-header"
import { MetricCard } from "@/components/ui/metric-card"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { DataTable } from "@/components/ui/data-table"
import { Badge } from "@/components/ui/badge"
import { RefreshCw, Loader2 } from "lucide-react"
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

export default function PortfolioOverview() {
  const [currency, setCurrency] = useState<"USD" | "CAD">("USD")
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
              <ResponsiveContainer width="100%" height={160}>
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

      {/* Value Breakdown + Allocation */}
      <div className="grid grid-cols-3 gap-4 mb-4">
        {positions.length > 0 && (
          <Card className="col-span-2">
            <CardTitle>Position Value Breakdown</CardTitle>
            <CardContent>
              <ResponsiveContainer width="100%" height={160}>
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
