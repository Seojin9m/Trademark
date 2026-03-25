import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { PortfolioData } from "@/lib/api"
import { formatCurrency, formatPercent, pnlColor, cn } from "@/lib/utils"
import { PageHeader } from "@/components/layout/page-header"
import { MetricCard } from "@/components/ui/metric-card"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { DataTable } from "@/components/ui/data-table"
import { Badge } from "@/components/ui/badge"
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

export default function PortfolioOverview() {
  const { data, isLoading, error } = useQuery<PortfolioData>({
    queryKey: ["portfolio"],
    queryFn: api.getPortfolio,
  })

  if (isLoading) {
    return (
      <>
        <PageHeader title="Portfolio Overview" />
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
    pnl: p.unrealized_pnl,
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
    value: p.market_value,
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
      render: (r: PositionRow) => <span>{formatCurrency(r.current_price)}</span>,
    },
    {
      key: "mktval",
      header: "Mkt Value",
      align: "right" as const,
      render: (r: PositionRow) => <span>{formatCurrency(r.market_value)}</span>,
    },
    {
      key: "pnl",
      header: "P&L",
      align: "right" as const,
      render: (r: PositionRow) => (
        <span className={cn("font-medium", pnlColor(r.unrealized_pnl))}>
          {formatCurrency(r.unrealized_pnl)}
        </span>
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
      <PageHeader title="Portfolio Overview" />

      {/* Metric Cards */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        <MetricCard
          label="Portfolio Value"
          value={formatCurrency(pnl.total_portfolio_value)}
        />
        <MetricCard
          label="Unrealized P&L"
          value={formatCurrency(pnl.total_unrealized_pnl)}
          delta={formatPercent(pnl.total_return_pct)}
          deltaValue={pnl.total_return_pct}
        />
        <MetricCard label="Cash" value={formatCurrency(pnl.cash)} />
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
                    formatter={(value: number) => [formatCurrency(value), "P&L"]}
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
                    formatter={(value: number) => [formatCurrency(value), "Market Value"]}
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
