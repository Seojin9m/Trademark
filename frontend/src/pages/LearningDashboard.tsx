import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { OutcomeSummary, DecisionOutcome, DecisionPattern, AdaptiveState } from "@/lib/api"
import { formatPercent, cn } from "@/lib/utils"
import { PageHeader } from "@/components/layout/page-header"
import { MetricCard } from "@/components/ui/metric-card"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { DataTable, type Column } from "@/components/ui/data-table"
import { SectionTitle } from "@/components/ui/section-title"
import { AlertTriangle } from "lucide-react"
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
  backgroundColor: "#0f1310",
  border: "1px solid #262d27",
  borderRadius: "6px",
  color: "#e8efe6",
  fontSize: "12px",
  fontFamily: "'JetBrains Mono', monospace",
  boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
}

const OUTCOME_COLORS: Record<string, string> = {
  GOOD: "#7ee787",
  BAD: "#ff6b6b",
  NEUTRAL: "#7a8479",
}

const STATUS_VARIANT: Record<string, "profit" | "loss" | "muted" | "default"> = {
  APPROVED: "profit",
  EXECUTED: "profit",
  JUDGE_APPROVED: "profit",
  REJECTED: "loss",
  JUDGE_REJECTED: "loss",
  NEEDS_REVIEW: "muted",
  PENDING: "default",
}

const outcomeColumns: Column<DecisionOutcome>[] = [
  {
    key: "decision_date",
    header: "Date",
    render: (r) => <span className="text-fg-dim">{r.decision_date?.slice(0, 10)}</span>,
  },
  {
    key: "ticker",
    header: "Ticker",
    render: (r) => <span className="font-semibold text-foreground">{r.ticker}</span>,
  },
  {
    key: "action",
    header: "Action",
    render: (r) => (
      <Badge variant={r.action === "BUY" || r.action === "ADD" ? "profit" : r.action === "SELL" || r.action === "EXIT" ? "loss" : "muted"}>
        {r.action}
      </Badge>
    ),
  },
  {
    key: "proposal_status",
    header: "Status",
    render: (r) => (
      <Badge variant={STATUS_VARIANT[r.proposal_status ?? ""] ?? "muted"}>
        {r.proposal_status ?? "—"}
      </Badge>
    ),
  },
  {
    key: "score_decile",
    header: "Decile",
    align: "right" as const,
    render: (r) => <span>{r.score_decile ?? "—"}</span>,
  },
  {
    key: "return_1m",
    header: "Return 1M",
    align: "right" as const,
    render: (r) => {
      const v = r.return_1m
      if (v == null) return <span className="text-muted-2">pending</span>
      const sign = v >= 0 ? "+" : ""
      return (
        <span className={cn(v > 0 ? "text-profit" : v < 0 ? "text-loss" : "text-fg-dim")}>
          {sign}{(v * 100).toFixed(2)}%
        </span>
      )
    },
  },
  {
    key: "excess_return_1m",
    header: "Excess 1M",
    align: "right" as const,
    render: (r) => {
      const v = r.excess_return_1m
      if (v == null) return <span className="text-muted-2">—</span>
      const sign = v >= 0 ? "+" : ""
      return (
        <span className={cn(v > 0 ? "text-profit" : v < 0 ? "text-loss" : "text-fg-dim")}>
          {sign}{(v * 100).toFixed(2)}%
        </span>
      )
    },
  },
  {
    key: "outcome_1m",
    header: "Outcome",
    render: (r) => {
      if (!r.outcome_1m) return <span className="text-muted-2">pending</span>
      return (
        <Badge variant={r.outcome_1m === "GOOD" ? "profit" : r.outcome_1m === "BAD" ? "loss" : "muted"}>
          {r.outcome_1m === "GOOD" ? "WIN" : r.outcome_1m === "BAD" ? "LOSS" : r.outcome_1m}
        </Badge>
      )
    },
  },
]

const patternColumns: Column<DecisionPattern>[] = [
  {
    key: "dimension",
    header: "Dimension",
    render: (r) => <span className="text-fg-dim">{r.dimension}</span>,
  },
  {
    key: "dimension_value",
    header: "Value",
    render: (r) => <span className="font-semibold text-foreground">{r.dimension_value}</span>,
  },
  {
    key: "sample_size",
    header: "Samples",
    align: "right" as const,
    render: (r) => <span>{r.sample_size}</span>,
  },
  {
    key: "win_rate",
    header: "Win Rate",
    align: "right" as const,
    render: (r) => (
      <span className={cn(
        r.win_rate != null && r.win_rate >= 0.5 ? "text-profit" : r.win_rate != null && r.win_rate < 0.4 ? "text-loss" : "text-fg-dim"
      )}>
        {r.win_rate != null ? formatPercent(r.win_rate) : "—"}
      </span>
    ),
  },
  {
    key: "avg_excess_return_1m",
    header: "Avg Excess 1M",
    align: "right" as const,
    render: (r) => {
      const v = r.avg_excess_return_1m
      if (v == null) return <span className="text-muted-2">—</span>
      const sign = v >= 0 ? "+" : ""
      return (
        <span className={cn(v > 0 ? "text-profit" : v < 0 ? "text-loss" : "text-fg-dim")}>
          {sign}{(v * 100).toFixed(2)}%
        </span>
      )
    },
  },
  {
    key: "best_ticker",
    header: "Best",
    render: (r) => <span className="text-profit font-semibold">{r.best_ticker ?? "—"}</span>,
  },
  {
    key: "worst_ticker",
    header: "Worst",
    render: (r) => <span className="text-loss font-semibold">{r.worst_ticker ?? "—"}</span>,
  },
  {
    key: "is_alert",
    header: "Alert",
    render: (r) => r.is_alert ? <Badge variant="loss">FLAGGED</Badge> : <span className="text-muted-2">—</span>,
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
        <PageHeader title="Self-Learning" description="Adaptive strategy · pattern detection across decisions" />
        <div className="grid grid-cols-5 gap-4 mb-[18px]">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="h-24 rounded-md border border-line bg-surface animate-shimmer" />
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
      fill: (p.win_rate ?? 0) >= 0.5 ? "#7ee787" : (p.win_rate ?? 0) < 0.4 ? "#ff6b6b" : "#7a8479",
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
      <PageHeader
        title="Self-Learning"
        description="Adaptive strategy · pattern detection across decisions"
      />

      {/* Summary Metrics */}
      <div className="grid grid-cols-5 gap-4 mb-[18px]">
        <MetricCard
          accent
          label="Signal Win Rate"
          value={summary?.win_rate != null ? formatPercent(summary.win_rate) : "—"}
          delta={summary?.classified ? `${summary.classified} measured` : undefined}
          deltaValue={summary?.win_rate != null && summary.win_rate >= 0.5 ? 1 : -1}
          sub="all proposals"
        />
        <MetricCard
          label="Avg Excess 1M"
          value={summary?.avg_excess_return_1m != null
            ? `${summary.avg_excess_return_1m >= 0 ? "+" : ""}${(summary.avg_excess_return_1m * 100).toFixed(2)}%`
            : "—"}
          valueNode={
            summary?.avg_excess_return_1m != null ? (
              <span className={cn(summary.avg_excess_return_1m > 0 ? "text-profit" : summary.avg_excess_return_1m < 0 ? "text-loss" : "")}>
                {summary.avg_excess_return_1m >= 0 ? "+" : ""}{(summary.avg_excess_return_1m * 100).toFixed(2)}%
              </span>
            ) : undefined
          }
          sub="vs benchmark"
        />
        <MetricCard
          label="Approved Win Rate"
          value={summary?.approved_win_rate != null ? formatPercent(summary.approved_win_rate) : "—"}
          valueNode={
            summary?.approved_win_rate != null ? (
              <span className={cn(summary.approved_win_rate >= 0.5 ? "text-profit" : "text-loss")}>
                {formatPercent(summary.approved_win_rate)}
              </span>
            ) : undefined
          }
          sub={summary?.approved_total ? `${summary.approved_total} trades` : undefined}
        />
        <MetricCard
          label="Rejected Win Rate"
          value={summary?.rejected_win_rate != null ? formatPercent(summary.rejected_win_rate) : "—"}
          valueNode={
            summary?.rejected_win_rate != null ? (
              <span className={cn(summary.rejected_win_rate < 0.5 ? "text-profit" : "text-loss")}>
                {formatPercent(summary.rejected_win_rate)}
              </span>
            ) : undefined
          }
          sub={summary?.rejected_total ? `${summary.rejected_total} · counter-evidence` : "counter-evidence"}
        />
        <MetricCard
          label="Pending"
          value={String(summary?.pending_measurement ?? 0)}
          sub="awaiting outcome"
        />
      </div>

      {/* Pattern Alerts */}
      {alerts && alerts.length > 0 && (
        <Card className="mb-4">
          <CardTitle meta={`${alerts.length} categor${alerts.length === 1 ? "y" : "ies"} with poor win rates`}>
            Pattern Alerts
          </CardTitle>
          <CardContent>
            <div className="flex flex-col gap-1.5">
              {alerts.map((a) => {
                const isHigh = (a.win_rate ?? 1) < 0.4
                return (
                  <div
                    key={a.pattern_id}
                    className={cn(
                      "flex items-center gap-2.5 p-2.5 rounded-[4px] border",
                      isHigh ? "border-loss/40 bg-loss/10" : "border-warn/40 bg-warn/10",
                    )}
                  >
                    <AlertTriangle className={cn("h-3.5 w-3.5 shrink-0", isHigh ? "text-loss" : "text-warn")} />
                    <span className="text-[12.5px] text-foreground/90 leading-[1.5]">
                      <strong className="font-semibold">{a.dimension_value}</strong>
                      {" "}({a.dimension}): {a.alert_message ?? `${formatPercent(a.win_rate ?? 0)} win rate over ${a.sample_size} trades`}
                    </span>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Adaptive Strategy */}
      {adaptive && adaptive.regime && (
        <>
          <SectionTitle>Adaptive Strategy</SectionTitle>
          <div className="grid grid-cols-3 gap-4 mb-[14px]">
            {/* Regime */}
            <Card>
              <CardTitle>Market Regime</CardTitle>
              <CardContent>
                <div className="flex flex-col gap-2.5 text-[12.5px]">
                  <div className="flex items-center">
                    <span className="font-mono text-muted-foreground" style={{ width: 110 }}>Volatility</span>
                    <Badge variant={adaptive.regime.vol_regime === "HIGH_VOL" ? "warn" : adaptive.regime.vol_regime === "LOW_VOL" ? "profit" : "muted"}>
                      {adaptive.regime.vol_regime}
                    </Badge>
                  </div>
                  <div className="flex items-center">
                    <span className="font-mono text-muted-foreground" style={{ width: 110 }}>Trend</span>
                    <Badge variant={adaptive.regime.momentum_regime === "BULL" ? "profit" : adaptive.regime.momentum_regime === "BEAR" ? "loss" : "muted"}>
                      {adaptive.regime.momentum_regime}
                    </Badge>
                  </div>
                  <div className="flex items-center">
                    <span className="font-mono text-muted-foreground" style={{ width: 110 }}>Score Disp</span>
                    <span className="font-mono text-foreground tabular-nums">
                      {adaptive.regime.score_dispersion.toFixed(2)}
                    </span>
                  </div>
                  <div className="flex items-center">
                    <span className="font-mono text-muted-foreground" style={{ width: 110 }}>Detected</span>
                    <span className="font-mono text-muted-2 text-[11px]">
                      {adaptive.computed_at?.slice(0, 16).replace("T", " ")}
                    </span>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Adaptive Constraints */}
            <Card>
              <CardTitle>Adaptive Constraints</CardTitle>
              <CardContent>
                <div className="flex flex-col gap-2 font-mono text-[12px]">
                  <div className="flex items-center">
                    <span className="flex-1 text-muted-foreground">Min decile threshold</span>
                    <span className="font-semibold text-primary tabular-nums">
                      ≤ {adaptive.min_decile_change}
                    </span>
                  </div>
                  <div className="flex items-center">
                    <span className="flex-1 text-muted-foreground">Position size scalar</span>
                    <span className="font-semibold text-primary tabular-nums">
                      {adaptive.position_size_scalar.toFixed(2)}×
                    </span>
                  </div>
                  <div className="flex items-center">
                    <span className="flex-1 text-muted-foreground">Max new positions</span>
                    <span className="font-semibold text-primary tabular-nums">
                      {adaptive.max_new_positions_per_run}
                    </span>
                  </div>
                  <div className="flex items-center">
                    <span className="flex-1 text-muted-foreground">Max trades per run</span>
                    <span className="font-semibold text-primary tabular-nums">
                      {adaptive.max_trades_per_run}
                    </span>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Factor Weights */}
            <Card>
              <CardTitle>Optimized Factor Weights</CardTitle>
              <CardContent>
                <div className="flex flex-col gap-2">
                  {Object.entries(adaptive.recommended_factor_weights).map(([factor, weight]) => {
                    const label = factor
                      .replace(/_/g, " ")
                      .replace(/12m1m/i, "12M-1M")
                      .replace(/yoy/i, "YoY")
                      .replace(/\b\w/g, (c) => c.toUpperCase())
                    return (
                      <div key={factor}>
                        <div className="flex font-mono text-[11.5px]">
                          <span className="flex-1 text-fg-dim">{label}</span>
                          <span className="font-semibold text-primary tabular-nums">
                            {(weight * 100).toFixed(0)}%
                          </span>
                        </div>
                        <div className="h-1 rounded-[2px] bg-line overflow-hidden mt-1">
                          <div
                            className="h-full bg-primary rounded-[2px] transition-all duration-500"
                            style={{ width: `${Math.min(100, weight * 100 * 2.5)}%` }}
                          />
                        </div>
                      </div>
                    )
                  })}
                </div>
                {adaptive.rationale && adaptive.rationale.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-line/40">
                    {adaptive.rationale.slice(0, 2).map((r, i) => (
                      <p key={i} className="text-[10.5px] text-muted-2 leading-[1.5]">{r}</p>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}

      {!hasData && (
        <Card className="mb-4">
          <CardContent>
            <div className="text-center py-12">
              <p className="text-sm text-muted-foreground">No proposal outcomes yet.</p>
              <p className="text-xs text-muted-2 mt-1">
                Run the pipeline to generate trade proposals. All proposals (approved and rejected)
                are tracked at 1-week, 1-month, and 3-month horizons.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {hasData && (
        <>
          {/* Charts Row */}
          <div className="grid grid-cols-2 gap-4 mb-4">
            <Card>
              <CardTitle meta={`${winRateByDimension.length} categor${winRateByDimension.length === 1 ? "y" : "ies"}`}>
                Win Rate by Category
              </CardTitle>
              <CardContent>
                {winRateByDimension.length > 0 ? (
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={winRateByDimension} margin={{ top: 10, right: 16, left: 0, bottom: 8 }}>
                      <CartesianGrid vertical={false} stroke="#1d231e" strokeDasharray="3 3" />
                      <XAxis
                        dataKey="label"
                        tick={{ fontSize: 10, fill: "#b3bcb1", fontWeight: 600 }}
                        axisLine={{ stroke: "#1d231e" }}
                        tickLine={false}
                        interval={0}
                        angle={winRateByDimension.length > 5 ? -25 : 0}
                        textAnchor={winRateByDimension.length > 5 ? "end" : "middle"}
                        height={winRateByDimension.length > 5 ? 50 : 28}
                      />
                      <YAxis
                        domain={[0, 100]}
                        tickFormatter={(v: number) => `${v}%`}
                        tick={{ fontSize: 10, fill: "#7a8479" }}
                        axisLine={false}
                        tickLine={false}
                        width={42}
                      />
                      <Tooltip
                        formatter={(value, _, props) =>
                          [`${Number(value).toFixed(0)}% (n=${(props as { payload: { samples: number } }).payload.samples})`, "Win Rate"]
                        }
                        contentStyle={tooltipStyle}
                        labelStyle={{ color: "#7a8479" }}
                        cursor={{ fill: "rgba(197, 251, 69, 0.06)" }}
                      />
                      <Bar dataKey="winRate" radius={[4, 4, 0, 0]} maxBarSize={32}>
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

            <Card>
              <CardTitle meta="x: date · y: excess return %">Outcome Timeline</CardTitle>
              <CardContent>
                {timelineData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={220}>
                    <ScatterChart margin={{ top: 10, right: 16, left: 0, bottom: 10 }}>
                      <CartesianGrid stroke="#1d231e" strokeDasharray="3 3" />
                      <XAxis
                        type="number"
                        dataKey="date"
                        domain={["auto", "auto"]}
                        tickFormatter={(v: number) => new Date(v).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                        tick={{ fontSize: 10, fill: "#7a8479" }}
                        axisLine={{ stroke: "#1d231e" }}
                        tickLine={false}
                      />
                      <YAxis
                        type="number"
                        dataKey="excess"
                        tickFormatter={(v: number) => `${v.toFixed(0)}%`}
                        tick={{ fontSize: 10, fill: "#7a8479" }}
                        axisLine={{ stroke: "#1d231e" }}
                        tickLine={false}
                        width={42}
                      />
                      <ZAxis range={[40, 40]} />
                      <Tooltip
                        formatter={(value) => [`${Number(value).toFixed(1)}%`, "Excess 1M"]}
                        labelFormatter={(v) => new Date(Number(v)).toLocaleDateString()}
                        contentStyle={tooltipStyle}
                        labelStyle={{ color: "#7a8479" }}
                        cursor={{ stroke: "#c5fb45", strokeWidth: 1, strokeDasharray: "4 2" }}
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

          {/* Patterns table */}
          <Card className="mb-4">
            <CardTitle meta={patterns ? `${patterns.length} pattern${patterns.length === 1 ? "" : "s"}` : undefined}>
              Decision Patterns
            </CardTitle>
            <DataTable
              columns={patternColumns}
              data={patterns ?? []}
              rowKey={(r) => r.pattern_id}
              emptyMessage="No patterns detected yet. Run the pipeline to build history."
              compact
            />
          </Card>
        </>
      )}

      {/* Outcomes table */}
      <Card>
        <CardTitle meta={outcomes ? `${outcomes.length} most recent` : undefined}>
          Proposal Outcomes
        </CardTitle>
        <DataTable
          columns={outcomeColumns}
          data={outcomes ?? []}
          rowKey={(r) => r.proposal_id}
          emptyMessage="No outcomes tracked yet. All proposals will appear here after pipeline runs."
          compact
        />
      </Card>
    </>
  )
}
