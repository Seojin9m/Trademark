import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "@/lib/api"
import type { RiskMetrics, PortfolioSnapshot } from "@/lib/api"
import { formatPercent, cn } from "@/lib/utils"
import { PageHeader } from "@/components/layout/page-header"
import { MetricCard } from "@/components/ui/metric-card"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from "recharts"

const tooltipStyle = {
  backgroundColor: "#0f1310",
  border: "1px solid #262d27",
  borderRadius: "6px",
  color: "#e8efe6",
  fontSize: "12px",
  fontFamily: "'JetBrains Mono', monospace",
  boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
}

function formatShortDate(dateStr: string): string {
  const [y, m, d] = dateStr.slice(0, 10).split("-").map(Number)
  const dt = new Date(y, m - 1, d)
  return dt.toLocaleDateString("en-US", { month: "2-digit", day: "2-digit" })
}

// Compute per-snapshot drawdown from peak (in percentage points). Returns the
// snapshots in chronological order with `drawdown` added.
function computeDrawdownSeries(snapshots: PortfolioSnapshot[]): Array<{
  date: string
  drawdown: number
}> {
  if (snapshots.length === 0) return []
  // Snapshots come newest-first from the API; reverse to chronological.
  const chrono = [...snapshots].reverse()
  let peak = chrono[0].total_value
  return chrono.map((s) => {
    if (s.total_value > peak) peak = s.total_value
    const dd = peak > 0 ? ((s.total_value - peak) / peak) * 100 : 0
    return {
      date: formatShortDate(s.snapshot_date),
      drawdown: +dd.toFixed(2),
    }
  })
}

export default function RiskMonitor() {
  const [currency, setCurrency] = useState<"USD" | "CAD">("CAD")

  const { data: risk, isLoading } = useQuery<RiskMetrics>({
    queryKey: ["risk"],
    queryFn: api.getRisk,
  })

  const { data: history } = useQuery<PortfolioSnapshot[]>({
    queryKey: ["portfolio-history"],
    queryFn: () => api.getPortfolioHistory(60),
    staleTime: 60 * 1000,
  })

  const { data: rateData } = useQuery({
    queryKey: ["exchange-rate"],
    queryFn: () => api.getExchangeRate("USD", "CAD"),
    staleTime: 5 * 60 * 1000,
  })

  const rate = currency === "CAD" ? (rateData?.rate ?? 1.38) : 1

  const fmtMoney = (value: number): string => {
    const v = value * rate
    const abs = Math.abs(v)
    const sign = v < 0 ? "-" : ""
    if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`
    if (abs >= 1_000) return `${sign}$${abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    return `${sign}$${abs.toFixed(2)}`
  }

  const currencyToggle = (
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

  if (isLoading) {
    return (
      <>
        <PageHeader title="Risk Monitor" actions={currencyToggle} />
        <div className="grid grid-cols-4 gap-4 mb-[18px]">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-24 rounded-md border border-line bg-surface animate-shimmer" />
          ))}
        </div>
        <div className="grid grid-cols-2 gap-4">
          {[0, 1].map((i) => (
            <div key={i} className="h-64 rounded-md border border-line bg-surface animate-shimmer" />
          ))}
        </div>
      </>
    )
  }

  if (!risk) {
    return (
      <PageHeader
        title="Risk Monitor"
        description="Failed to load risk data."
        actions={currencyToggle}
      />
    )
  }

  const alertPctNum = risk.drawdown_alert_level * 100
  const haltPctNum = risk.drawdown_halt_level * 100

  const ddSeries = computeDrawdownSeries(history ?? [])
  const ddMin = ddSeries.length > 0 ? Math.min(...ddSeries.map((d) => d.drawdown)) : 0
  // Current drawdown = peak-to-current from history if we have data,
  // otherwise fall back to total_return_pct (which is current return from
  // cost basis — close enough when no history exists).
  const currentDrawdown = ddSeries.length > 0
    ? ddSeries[ddSeries.length - 1].drawdown
    : (risk.total_return_pct < 0 ? risk.total_return_pct * 100 : 0)

  const isHalt = currentDrawdown < haltPctNum
  const isAlert = !isHalt && currentDrawdown < alertPctNum
  const statusLabel = isHalt ? "STATUS: HALT" : isAlert ? "STATUS: ALERT" : "STATUS: OK"
  const deltaValue = isHalt ? -1 : isAlert ? -0.5 : 1

  const cashDollar = risk.portfolio_value * risk.cash_pct
  const sectorCount = Object.keys(risk.sector_weights).length

  const sectorData = Object.entries(risk.sector_weights)
    .map(([sector, weight]) => ({ sector, weight: weight * 100 }))
    .sort((a, b) => b.weight - a.weight)

  const ddDomainBottom = Math.min(ddMin, haltPctNum) * 1.1
  const drawdownColor = isHalt ? "#ff6b6b" : isAlert ? "#fbbf24" : "#7ee787"

  return (
    <>
      <PageHeader
        title="Risk Monitor"
        description="Drawdown, exposure, and concentration tracking"
        actions={currencyToggle}
      />

      <div className="grid grid-cols-4 gap-4 mb-[18px]">
        <MetricCard
          accent
          label="Portfolio Drawdown"
          value={`${currentDrawdown.toFixed(2)}%`}
          valueNode={
            <span className={cn(isHalt ? "text-loss" : isAlert ? "text-warn" : "text-profit")}>
              {currentDrawdown.toFixed(2)}%
            </span>
          }
          delta={statusLabel}
          deltaValue={deltaValue}
          sub={`${alertPctNum.toFixed(0)}% alert · ${haltPctNum.toFixed(0)}% halt`}
        />
        <MetricCard
          label={`Portfolio Value (${currency})`}
          value={fmtMoney(risk.portfolio_value)}
          sub={`${risk.n_positions} position${risk.n_positions === 1 ? "" : "s"}`}
        />
        <MetricCard
          label="Cash Allocation"
          value={formatPercent(risk.cash_pct)}
          sub={fmtMoney(cashDollar)}
        />
        <MetricCard
          label="Position Count"
          value={String(risk.n_positions)}
          sub={sectorCount > 0 ? `across ${sectorCount} sector${sectorCount === 1 ? "" : "s"}` : undefined}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardTitle meta={ddSeries.length > 0 ? `trailing ${ddSeries.length} sessions` : undefined}>
            Drawdown Progression
          </CardTitle>
          <CardContent>
            {ddSeries.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-12">
                No history yet — run the pipeline to start tracking.
              </p>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart
                  data={ddSeries}
                  margin={{ top: 10, right: 16, left: 0, bottom: 6 }}
                >
                  <defs>
                    <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={drawdownColor} stopOpacity={0.05} />
                      <stop offset="100%" stopColor={drawdownColor} stopOpacity={0.35} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} stroke="#1d231e" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10, fill: "#7a8479" }}
                    axisLine={{ stroke: "#1d231e" }}
                    tickLine={false}
                    interval="preserveStartEnd"
                    minTickGap={24}
                  />
                  <YAxis
                    domain={[ddDomainBottom, 0]}
                    tickFormatter={(v: number) => `${v.toFixed(1)}%`}
                    tick={{ fontSize: 10, fill: "#7a8479" }}
                    axisLine={false}
                    tickLine={false}
                    width={50}
                  />
                  <Tooltip
                    formatter={(v) => [`${Number(v).toFixed(2)}%`, "Drawdown"]}
                    contentStyle={tooltipStyle}
                    labelStyle={{ color: "#7a8479" }}
                    cursor={{ stroke: drawdownColor, strokeWidth: 1, strokeDasharray: "4 2" }}
                  />
                  <ReferenceLine
                    y={alertPctNum}
                    stroke="#fbbf24"
                    strokeDasharray="4 4"
                    strokeWidth={1}
                    label={{ value: `Alert ${alertPctNum.toFixed(0)}%`, fill: "#fbbf24", fontSize: 9, position: "insideTopRight" }}
                  />
                  <ReferenceLine
                    y={haltPctNum}
                    stroke="#ff6b6b"
                    strokeDasharray="4 4"
                    strokeWidth={1}
                    label={{ value: `Halt ${haltPctNum.toFixed(0)}%`, fill: "#ff6b6b", fontSize: 9, position: "insideBottomRight" }}
                  />
                  <Area
                    type="monotone"
                    dataKey="drawdown"
                    stroke={drawdownColor}
                    strokeWidth={2}
                    fill="url(#ddGrad)"
                    dot={false}
                    activeDot={{ r: 4, fill: drawdownColor, stroke: "#0f1310", strokeWidth: 2 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardTitle meta="% of portfolio">Sector Weight Breakdown</CardTitle>
          <CardContent>
            {sectorData.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-12">No sector data</p>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={sectorData} margin={{ top: 16, right: 12, left: 0, bottom: 12 }}>
                  <CartesianGrid vertical={false} stroke="#1d231e" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="sector"
                    tick={{ fontSize: 10, fill: "#b3bcb1", fontWeight: 600 }}
                    axisLine={{ stroke: "#1d231e" }}
                    tickLine={false}
                    interval={0}
                    angle={sectorData.length > 5 ? -25 : 0}
                    textAnchor={sectorData.length > 5 ? "end" : "middle"}
                    height={sectorData.length > 5 ? 50 : 28}
                  />
                  <YAxis
                    tickFormatter={(v: number) => `${v.toFixed(0)}%`}
                    tick={{ fontSize: 10, fill: "#7a8479" }}
                    axisLine={false}
                    tickLine={false}
                    width={42}
                  />
                  <Tooltip
                    formatter={(v) => [`${Number(v).toFixed(1)}%`, "Weight"]}
                    contentStyle={tooltipStyle}
                    labelStyle={{ color: "#7a8479" }}
                    cursor={{ fill: "rgba(197, 251, 69, 0.06)" }}
                  />
                  <ReferenceLine
                    y={35}
                    stroke="#ff6b6b"
                    strokeDasharray="4 4"
                    strokeWidth={1}
                    label={{ value: "35% Limit", fill: "#ff6b6b", fontSize: 9, position: "insideTopRight" }}
                  />
                  <Bar dataKey="weight" radius={[4, 4, 0, 0]} maxBarSize={48}>
                    {sectorData.map((d, i) => (
                      <Cell key={i} fill={d.weight > 35 ? "#ff6b6b" : "#c5fb45"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  )
}
