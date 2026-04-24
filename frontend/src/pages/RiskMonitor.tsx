import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { RiskMetrics } from "@/lib/api"
import { formatCurrency, formatPercent, cn } from "@/lib/utils"
import { PageHeader } from "@/components/layout/page-header"
import { MetricCard } from "@/components/ui/metric-card"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { ShieldAlert, ShieldCheck, ShieldX } from "lucide-react"
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts"

const tooltipStyle = {
  backgroundColor: "#111113",
  border: "1px solid #1f1f2e",
  borderRadius: "0.75rem",
  color: "#fafafa",
  fontSize: "12px",
  boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
}

export default function RiskMonitor() {
  const { data: risk, isLoading } = useQuery<RiskMetrics>({
    queryKey: ["risk"],
    queryFn: api.getRisk,
  })

  if (isLoading) {
    return (
      <>
        <PageHeader title="Risk Monitor" />
        <div className="grid grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-28 rounded-xl border border-border/60 bg-card animate-shimmer" />
          ))}
        </div>
      </>
    )
  }

  if (!risk) {
    return (
      <PageHeader title="Risk Monitor" description="Failed to load risk data." />
    )
  }

  const drawdown = risk.total_return_pct < 0 ? risk.total_return_pct : 0
  const drawdownPct = Math.abs(drawdown * 100)
  const alertPct = Math.abs(risk.drawdown_alert_level * 100)
  const haltPct = Math.abs(risk.drawdown_halt_level * 100)

  const isAlert = drawdown < risk.drawdown_alert_level
  const isHalt = drawdown < risk.drawdown_halt_level

  const sectorData = Object.entries(risk.sector_weights).map(([sector, weight]) => ({
    sector,
    weight,
  }))

  const statusColor = isHalt ? "text-loss" : isAlert ? "text-warn" : "text-profit"
  const statusLabel = isHalt ? "HALT" : isAlert ? "ALERT" : "OK"

  return (
    <>
      <PageHeader title="Risk Monitor" />

      <div className="grid grid-cols-4 gap-4 mb-6">
        <MetricCard
          label="Portfolio Drawdown"
          value={formatPercent(drawdown)}
          delta={statusLabel}
          deltaValue={isHalt ? -1 : isAlert ? -0.5 : 1}
        />
        <MetricCard label="Portfolio Value" value={formatCurrency(risk.portfolio_value)} />
        <MetricCard label="Cash Allocation" value={formatPercent(risk.cash_pct)} />
        <MetricCard label="Positions" value={String(risk.n_positions)} />
      </div>

      {/* Status Banner */}
      {isHalt && (
        <div className="mb-6 flex items-center gap-3 rounded-xl bg-loss/10 border border-loss/30 p-4">
          <ShieldX className="h-5 w-5 text-loss shrink-0" />
          <div>
            <p className="text-sm font-semibold text-loss">Drawdown Halt Active</p>
            <p className="text-xs text-loss/80">All new positions require manual confirmation.</p>
          </div>
        </div>
      )}
      {isAlert && !isHalt && (
        <div className="mb-6 flex items-center gap-3 rounded-xl bg-warn/10 border border-warn/30 p-4">
          <ShieldAlert className="h-5 w-5 text-warn shrink-0" />
          <div>
            <p className="text-sm font-semibold text-warn">Drawdown Alert</p>
            <p className="text-xs text-warn/80">New buy signals are blocked until drawdown recovers.</p>
          </div>
        </div>
      )}
      {!isAlert && !isHalt && (
        <div className="mb-6 flex items-center gap-3 rounded-xl bg-profit/10 border border-profit/30 p-4">
          <ShieldCheck className="h-5 w-5 text-profit shrink-0" />
          <div>
            <p className="text-sm font-semibold text-profit">All Clear</p>
            <p className="text-xs text-profit/80">Drawdown within acceptable limits.</p>
          </div>
        </div>
      )}

      {/* Drawdown Gauge */}
      <Card className="mb-6">
        <CardTitle>Drawdown Gauge</CardTitle>
        <CardContent>
          <div className="relative">
            <div className="h-3 rounded-full bg-muted/60 overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-700 ease-out",
                  isHalt ? "bg-loss" : isAlert ? "bg-warn" : "bg-profit",
                )}
                style={{ width: `${Math.min((drawdownPct / haltPct) * 100, 100)}%` }}
              />
            </div>
            {/* Alert marker */}
            <div
              className="absolute top-0 h-3 border-r-2 border-warn border-dashed"
              style={{ left: `${(alertPct / haltPct) * 100}%` }}
            />
            {/* Halt marker */}
            <div className="absolute top-0 right-0 h-3 border-r-2 border-loss" />
          </div>
          <div className="flex justify-between mt-2 text-xs">
            <span className="text-muted-foreground">0%</span>
            <span className="text-muted-foreground">
              Current: <span className={cn("font-medium", statusColor)}>{drawdownPct.toFixed(1)}%</span>
            </span>
          </div>
          <div className="flex justify-between mt-1 text-[11px]">
            <span />
            <div className="flex gap-6">
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-2 w-2 rounded-full bg-warn" />
                <span className="text-muted-foreground">Alert {alertPct.toFixed(0)}%</span>
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-2 w-2 rounded-full bg-loss" />
                <span className="text-muted-foreground">Halt {haltPct.toFixed(0)}%</span>
              </span>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-6">
        <Card>
          <CardTitle>Sector Concentration</CardTitle>
          <CardContent>
            {sectorData.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={sectorData} layout="vertical">
                  <XAxis
                    type="number"
                    tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                    domain={[0, 0.4]}
                    tick={{ fontSize: 11, fill: "#71717a" }}
                    axisLine={{ stroke: "#27272a" }}
                    tickLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="sector"
                    width={120}
                    tick={{ fontSize: 12, fill: "#a1a1aa" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    formatter={(value) => formatPercent(Number(value))}
                    contentStyle={tooltipStyle}
                  />
                  <Bar dataKey="weight" fill="#6366f1" radius={[0, 6, 6, 0]} />
                  <ReferenceLine
                    x={0.35}
                    stroke="#ef4444"
                    strokeDasharray="4 4"
                    label={{ value: "35% Limit", fill: "#ef4444", fontSize: 10 }}
                  />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-12">No sector data</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardTitle>Portfolio Summary</CardTitle>
          <CardContent>
            <div className="space-y-4">
              {[
                ["Portfolio Value", formatCurrency(risk.portfolio_value)],
                ["Unrealized P&L", formatCurrency(risk.unrealized_pnl)],
                ["Total Return", formatPercent(risk.total_return_pct)],
                ["Cash %", formatPercent(risk.cash_pct)],
                ["Positions", String(risk.n_positions)],
                ["Alert Level", formatPercent(risk.drawdown_alert_level)],
                ["Halt Level", formatPercent(risk.drawdown_halt_level)],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between items-center text-sm">
                  <span className="text-muted-foreground">{label}</span>
                  <span className="font-medium">{value}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  )
}
