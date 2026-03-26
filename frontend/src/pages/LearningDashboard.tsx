import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { OutcomeSummary, DecisionOutcome, DecisionPattern, AdaptiveState } from "@/lib/api"
import { formatPercent, cn } from "@/lib/utils"
import { PageHeader } from "@/components/layout/page-header"
import { MetricCard } from "@/components/ui/metric-card"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { DataTable, type Column } from "@/components/ui/data-table"
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ScatterChart,
  Scatter,
  CartesianGrid,
  ZAxis,
} from "recharts"

const tooltipStyle = {
  backgroundColor: "#111113",
  border: "1px solid #1f1f2e",
  borderRadius: "0.75rem",
  color: "#fafafa",
  fontSize: "12px",
  boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
}

const OUTCOME_COLORS: Record<string, string> = {
  GOOD: "#22c55e",
  BAD: "#ef4444",
  NEUTRAL: "#71717a",
}

const outcomeColumns: Column<DecisionOutcome>[] = [
  {
    key: "decision_date",
    header: "Date",
    render: (r) => <span className="text-muted-foreground text-xs">{r.decision_date?.slice(0, 10)}</span>,
  },
  {
    key: "ticker",
    header: "Ticker",
    render: (r) => <span className="font-medium">{r.ticker}</span>,
  },
  {
    key: "action",
    header: "Action",
    render: (r) => (
      <Badge variant={r.action === "BUY" ? "default" : r.action === "SELL" ? "loss" : "muted"}>
        {r.action}
      </Badge>
    ),
  },
  {
    key: "score_decile",
    header: "Decile",
    render: (r) => <span>{r.score_decile ?? "-"}</span>,
  },
  {
    key: "judge_verdict",
    header: "Verdict",
    render: (r) => <span className="text-xs text-muted-foreground">{r.judge_verdict ?? "-"}</span>,
  },
  {
    key: "return_1m",
    header: "Return 1M",
    render: (r) => (
      <span className={cn(r.return_1m != null && r.return_1m > 0 ? "text-profit" : r.return_1m != null && r.return_1m < 0 ? "text-loss" : "text-muted-foreground")}>
        {r.return_1m != null ? formatPercent(r.return_1m) : "pending"}
      </span>
    ),
  },
  {
    key: "excess_return_1m",
    header: "Excess 1M",
    render: (r) => (
      <span className={cn(r.excess_return_1m != null && r.excess_return_1m > 0 ? "text-profit" : r.excess_return_1m != null && r.excess_return_1m < 0 ? "text-loss" : "text-muted-foreground")}>
        {r.excess_return_1m != null ? formatPercent(r.excess_return_1m) : "-"}
      </span>
    ),
  },
  {
    key: "outcome_1m",
    header: "Outcome",
    render: (r) => {
      if (!r.outcome_1m) return <span className="text-xs text-muted-foreground">pending</span>
      return (
        <Badge
          variant={r.outcome_1m === "GOOD" ? "profit" : r.outcome_1m === "BAD" ? "loss" : "muted"}
        >
          {r.outcome_1m}
        </Badge>
      )
    },
  },
]

const patternColumns: Column<DecisionPattern>[] = [
  {
    key: "dimension",
    header: "Dimension",
    render: (r) => <span className="text-xs text-muted-foreground">{r.dimension}</span>,
  },
  {
    key: "dimension_value",
    header: "Value",
    render: (r) => <span className="font-medium">{r.dimension_value}</span>,
  },
  {
    key: "sample_size",
    header: "Samples",
    render: (r) => <span>{r.sample_size}</span>,
  },
  {
    key: "win_rate",
    header: "Win Rate",
    render: (r) => (
      <span className={cn(
        r.win_rate != null && r.win_rate >= 0.5 ? "text-profit" : r.win_rate != null && r.win_rate < 0.4 ? "text-loss" : "text-foreground"
      )}>
        {r.win_rate != null ? formatPercent(r.win_rate) : "-"}
      </span>
    ),
  },
  {
    key: "avg_excess_return_1m",
    header: "Avg Excess 1M",
    render: (r) => (
      <span className={cn(
        r.avg_excess_return_1m != null && r.avg_excess_return_1m > 0 ? "text-profit" : r.avg_excess_return_1m != null && r.avg_excess_return_1m < 0 ? "text-loss" : "text-muted-foreground"
      )}>
        {r.avg_excess_return_1m != null ? formatPercent(r.avg_excess_return_1m) : "-"}
      </span>
    ),
  },
  {
    key: "best_ticker",
    header: "Best",
    render: (r) => <span className="text-profit text-xs">{r.best_ticker ?? "-"}</span>,
  },
  {
    key: "worst_ticker",
    header: "Worst",
    render: (r) => <span className="text-loss text-xs">{r.worst_ticker ?? "-"}</span>,
  },
  {
    key: "is_alert",
    header: "Alert",
    render: (r) => r.is_alert ? <Badge variant="loss">ALERT</Badge> : null,
  },
]

export default function LearningDashboard() {
  const { data: summary, isLoading: summaryLoading } = useQuery<OutcomeSummary>({
    queryKey: ["learning-summary"],
    queryFn: api.getLearningSummary,
  })

  const { data: outcomes } = useQuery<DecisionOutcome[]>({
    queryKey: ["learning-outcomes"],
    queryFn: () => api.getLearningOutcomes(100),
  })

  const { data: patterns } = useQuery<DecisionPattern[]>({
    queryKey: ["learning-patterns"],
    queryFn: api.getLearningPatterns,
  })

  const { data: alerts } = useQuery<DecisionPattern[]>({
    queryKey: ["learning-alerts"],
    queryFn: api.getLearningAlerts,
  })

  const { data: adaptive } = useQuery<AdaptiveState>({
    queryKey: ["adaptive-state"],
    queryFn: api.getAdaptiveState,
  })

  if (summaryLoading) {
    return (
      <>
        <PageHeader title="Self-Learning" />
        <div className="grid grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-28 rounded-xl border border-border/60 bg-card animate-shimmer" />
          ))}
        </div>
      </>
    )
  }

  const hasData = summary && summary.total_decisions > 0
  const classifiedOutcomes = outcomes?.filter((o) => o.outcome_1m) ?? []

  // Win rate by dimension chart data
  const winRateByDimension = patterns
    ?.filter((p) => p.dimension !== "overall" && p.sample_size >= 3 && p.win_rate != null)
    .map((p) => ({
      label: `${p.dimension_value}`,
      winRate: (p.win_rate ?? 0) * 100,
      samples: p.sample_size,
      fill: (p.win_rate ?? 0) >= 0.5 ? "#22c55e" : (p.win_rate ?? 0) < 0.4 ? "#ef4444" : "#71717a",
    })) ?? []

  // Outcome timeline scatter data
  const timelineData = classifiedOutcomes.map((o) => ({
    date: new Date(o.decision_date).getTime(),
    excess: (o.excess_return_1m ?? 0) * 100,
    ticker: o.ticker,
    outcome: o.outcome_1m,
    fill: OUTCOME_COLORS[o.outcome_1m ?? "NEUTRAL"],
  }))

  return (
    <>
      <PageHeader title="Self-Learning" />

      {/* Summary Metrics */}
      <div className="grid grid-cols-5 gap-4 mb-4">
        <MetricCard
          label="Win Rate"
          value={summary?.win_rate != null ? formatPercent(summary.win_rate) : "—"}
          delta={summary?.classified ? `${summary.classified} classified` : undefined}
          deltaValue={summary?.win_rate != null && summary.win_rate >= 0.5 ? 1 : -1}
        />
        <MetricCard
          label="Avg Excess 1M"
          value={summary?.avg_excess_return_1m != null ? formatPercent(summary.avg_excess_return_1m) : "—"}
          deltaValue={summary?.avg_excess_return_1m != null ? summary.avg_excess_return_1m : 0}
        />
        <MetricCard
          label="Good Decisions"
          value={String(summary?.good ?? 0)}
          delta={`of ${summary?.classified ?? 0}`}
          deltaValue={1}
        />
        <MetricCard
          label="Bad Decisions"
          value={String(summary?.bad ?? 0)}
          delta={`of ${summary?.classified ?? 0}`}
          deltaValue={-1}
        />
        <MetricCard
          label="Pending"
          value={String(summary?.pending_measurement ?? 0)}
          delta="awaiting measurement"
        />
      </div>

      {/* Alerts Banner */}
      {alerts && alerts.length > 0 && (
        <div className="mb-4 space-y-2">
          {alerts.map((a) => (
            <div key={a.pattern_id} className="flex items-center gap-3 rounded-xl bg-loss/10 border border-loss/30 p-3">
              <span className="text-loss text-sm font-medium">Alert:</span>
              <span className="text-sm text-loss/80">{a.alert_message}</span>
            </div>
          ))}
        </div>
      )}

      {/* Adaptive Strategy Panel */}
      {adaptive && adaptive.regime && (
        <div className="grid grid-cols-3 gap-4 mb-4">
          {/* Regime */}
          <Card>
            <CardTitle>Market Regime</CardTitle>
            <CardContent>
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Volatility</span>
                  <Badge variant={adaptive.regime.vol_regime === "HIGH_VOL" ? "loss" : adaptive.regime.vol_regime === "LOW_VOL" ? "profit" : "muted"}>
                    {adaptive.regime.vol_regime} ({formatPercent(adaptive.regime.realized_vol)})
                  </Badge>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Trend</span>
                  <Badge variant={adaptive.regime.momentum_regime === "BULL" ? "profit" : adaptive.regime.momentum_regime === "BEAR" ? "loss" : "muted"}>
                    {adaptive.regime.momentum_regime} ({adaptive.regime.momentum_21d >= 0 ? "+" : ""}{formatPercent(adaptive.regime.momentum_21d)})
                  </Badge>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Score Dispersion</span>
                  <span className="text-sm">{adaptive.regime.score_dispersion.toFixed(2)}</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Adaptive Constraints */}
          <Card>
            <CardTitle>Adaptive Constraints</CardTitle>
            <CardContent>
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Decile Threshold</span>
                  <span className="text-sm font-medium">{adaptive.min_decile_change}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Position Scalar</span>
                  <span className={cn("text-sm font-medium", adaptive.position_size_scalar < 1 ? "text-loss" : adaptive.position_size_scalar > 1 ? "text-profit" : "")}>
                    {formatPercent(adaptive.position_size_scalar)}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Max New Positions</span>
                  <span className="text-sm font-medium">{adaptive.max_new_positions_per_run}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Max Trades/Run</span>
                  <span className="text-sm font-medium">{adaptive.max_trades_per_run}</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Factor Weights */}
          <Card>
            <CardTitle>Optimized Factor Weights</CardTitle>
            <CardContent>
              <div className="space-y-2">
                {Object.entries(adaptive.recommended_factor_weights).map(([factor, weight]) => {
                  const label = factor.replace(/_/g, " ").replace(/12m1m/, "12M-1M").replace(/yoy/, "YoY")
                  return (
                    <div key={factor} className="flex items-center gap-2">
                      <div className="flex-1">
                        <div className="flex justify-between text-xs mb-0.5">
                          <span className="text-muted-foreground capitalize">{label}</span>
                          <span>{formatPercent(weight)}</span>
                        </div>
                        <div className="h-1.5 rounded-full bg-muted/60 overflow-hidden">
                          <div
                            className="h-full rounded-full bg-primary transition-all duration-500"
                            style={{ width: `${weight * 100 * 5}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
              {adaptive.rationale && adaptive.rationale.length > 0 && (
                <div className="mt-3 pt-3 border-t border-border/40">
                  {adaptive.rationale.map((r, i) => (
                    <p key={i} className="text-[11px] text-muted-foreground/70 leading-relaxed">{r}</p>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {!hasData && (
        <Card className="mb-4">
          <CardContent>
            <div className="text-center py-12">
              <p className="text-muted-foreground text-sm">No decision outcomes yet.</p>
              <p className="text-muted-foreground/60 text-xs mt-1">
                Run the pipeline to generate trade proposals. Outcomes will be measured at 1-week, 1-month, and 3-month horizons.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {hasData && (
        <>
          {/* Charts Row */}
          <div className="grid grid-cols-2 gap-4 mb-4">
            {/* Win Rate by Dimension */}
            <Card>
              <CardTitle>Win Rate by Category</CardTitle>
              <CardContent>
                {winRateByDimension.length > 0 ? (
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={winRateByDimension} layout="vertical" margin={{ left: 10, right: 20 }}>
                      <CartesianGrid horizontal={false} stroke="#1f1f2e" strokeDasharray="3 3" />
                      <XAxis
                        type="number"
                        domain={[0, 100]}
                        tickFormatter={(v: number) => `${v}%`}
                        tick={{ fontSize: 11, fill: "#71717a" }}
                        axisLine={{ stroke: "#27272a" }}
                        tickLine={false}
                      />
                      <YAxis
                        type="category"
                        dataKey="label"
                        width={100}
                        tick={{ fontSize: 11, fill: "#a1a1aa" }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip
                        formatter={(value: number, _: string, props: { payload: { samples: number } }) =>
                          [`${value.toFixed(0)}% (n=${props.payload.samples})`, "Win Rate"]
                        }
                        contentStyle={tooltipStyle}
                        labelStyle={{ color: "#a1a1aa" }}
                        itemStyle={{ color: "#fafafa" }}
                      />
                      <Bar dataKey="winRate" radius={[0, 4, 4, 0]} maxBarSize={18}>
                        {winRateByDimension.map((entry, i) => (
                          <Cell key={i} fill={entry.fill} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <p className="text-sm text-muted-foreground text-center py-8">Not enough data</p>
                )}
              </CardContent>
            </Card>

            {/* Outcome Timeline */}
            <Card>
              <CardTitle>Outcome Timeline</CardTitle>
              <CardContent>
                {timelineData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={200}>
                    <ScatterChart margin={{ left: 10, right: 20, top: 10, bottom: 10 }}>
                      <CartesianGrid stroke="#1f1f2e" strokeDasharray="3 3" />
                      <XAxis
                        type="number"
                        dataKey="date"
                        domain={["auto", "auto"]}
                        tickFormatter={(v: number) => new Date(v).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                        tick={{ fontSize: 11, fill: "#71717a" }}
                        axisLine={{ stroke: "#27272a" }}
                        tickLine={false}
                      />
                      <YAxis
                        type="number"
                        dataKey="excess"
                        tickFormatter={(v: number) => `${v.toFixed(0)}%`}
                        tick={{ fontSize: 11, fill: "#71717a" }}
                        axisLine={{ stroke: "#27272a" }}
                        tickLine={false}
                      />
                      <ZAxis range={[40, 40]} />
                      <Tooltip
                        formatter={(value: number) => [`${value.toFixed(1)}%`, "Excess Return 1M"]}
                        labelFormatter={(v: number) => new Date(v).toLocaleDateString()}
                        contentStyle={tooltipStyle}
                        labelStyle={{ color: "#a1a1aa" }}
                        itemStyle={{ color: "#fafafa" }}
                      />
                      <Scatter data={timelineData} shape="circle">
                        {timelineData.map((entry, i) => (
                          <Cell key={i} fill={entry.fill} />
                        ))}
                      </Scatter>
                    </ScatterChart>
                  </ResponsiveContainer>
                ) : (
                  <p className="text-sm text-muted-foreground text-center py-8">No classified outcomes yet</p>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Patterns Table */}
          <Card className="mb-4">
            <CardTitle>Decision Patterns</CardTitle>
            <CardContent>
              <DataTable
                columns={patternColumns}
                data={patterns ?? []}
                rowKey={(r) => r.pattern_id}
                emptyMessage="No patterns detected yet. Run the pipeline to build history."
              />
            </CardContent>
          </Card>
        </>
      )}

      {/* Outcomes Table */}
      <Card>
        <CardTitle>Decision Outcomes</CardTitle>
        <CardContent>
          <DataTable
            columns={outcomeColumns}
            data={outcomes ?? []}
            rowKey={(r) => r.proposal_id}
            emptyMessage="No outcomes tracked yet. Proposals will appear here after pipeline runs."
          />
        </CardContent>
      </Card>
    </>
  )
}
