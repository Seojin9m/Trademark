import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { Proposal, JudgeLogEntry } from "@/lib/api"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { DataTable } from "@/components/ui/data-table"
import { MetricCard } from "@/components/ui/metric-card"
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts"

type StatusVariant = "profit" | "loss" | "warn" | "accent" | "muted"

// Colors for known verdict types. Per-proposal verdicts are approve/reject/
// needs_review; portfolio-level verdicts are agree/disagree (judge weighing
// in on the pipeline's overall HOLD/STAY decision). Any unknown verdict
// falls back to a neutral gray so the pie still renders sensibly.
const VERDICT_COLORS: Record<string, string> = {
  approve: "#7ee787",
  agree: "#7ee787",
  reject: "#ff6b6b",
  disagree: "#fbbf24",
  needs_review: "#fbbf24",
  review: "#fbbf24",
}
const FALLBACK_VERDICT_COLOR = "#525a52"

const tooltipStyle = {
  backgroundColor: "#0f1310",
  border: "1px solid #262d27",
  borderRadius: "6px",
  color: "#e8efe6",
  fontSize: "12px",
  fontFamily: "'JetBrains Mono', monospace",
  boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
}

function statusVariant(status: string): StatusVariant {
  switch (status) {
    case "EXECUTED":
    case "APPROVED":
      return "profit"
    case "REJECTED":
    case "JUDGE_REJECTED":
      return "loss"
    case "JUDGE_APPROVED":
      return "accent"
    case "PENDING":
    case "NEEDS_REVIEW":
      return "warn"
    default:
      return "muted"
  }
}

function verdictVariant(verdict: string): StatusVariant {
  const v = verdict.toLowerCase()
  if (v === "approve") return "profit"
  if (v === "reject") return "loss"
  if (v === "needs_review") return "warn"
  return "muted"
}

function formatDate(ts: string): string {
  if (!ts) return ""
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ts.slice(0, 10)
  return d.toISOString().slice(0, 10)
}

function formatDateTime(ts: string): string {
  if (!ts) return ""
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ts
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, "0")
  const dd = String(d.getDate()).padStart(2, "0")
  const hh = String(d.getHours()).padStart(2, "0")
  const mi = String(d.getMinutes()).padStart(2, "0")
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`
}

export default function DecisionLog() {
  const { data: proposals, isLoading: loadingProposals } = useQuery<Proposal[]>({
    queryKey: ["proposals-log"],
    queryFn: () => api.getProposals(undefined, 20),
  })

  const { data: judgeLog, isLoading: loadingJudge } = useQuery<JudgeLogEntry[]>({
    queryKey: ["judge-log"],
    queryFn: () => api.getJudgeLog(50),
  })

  if (loadingProposals || loadingJudge) {
    return (
      <>
        <PageHeader title="Decision Log" />
        <div className="grid grid-cols-4 gap-4 mb-[18px]">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-24 rounded-md border border-line bg-surface animate-shimmer" />
          ))}
        </div>
        <div className="space-y-4">
          {[0, 1].map((i) => (
            <div key={i} className="h-48 rounded-md border border-line bg-surface animate-shimmer" />
          ))}
        </div>
      </>
    )
  }

  const allProposals = proposals || []
  const allJudge = judgeLog || []

  const verdictCounts = allJudge.reduce<Record<string, number>>((acc, e) => {
    const k = e.verdict.toLowerCase()
    acc[k] = (acc[k] || 0) + 1
    return acc
  }, {})

  const totalVerdicts = allJudge.length

  // Approved / rejected groupings combine per-proposal and portfolio-level
  // semantics so the metric cards still show meaningful numbers regardless of
  // whether the judge was reviewing trades or a HOLD decision.
  const approvedCount = (verdictCounts.approve || 0) + (verdictCounts.agree || 0)
  const rejectedCount = (verdictCounts.reject || 0) + (verdictCounts.disagree || 0)
  const reviewCount = (verdictCounts.needs_review || 0) + (verdictCounts.review || 0)

  // Build pie data dynamically from whatever verdicts exist, sorted by count.
  const pieData = Object.entries(verdictCounts)
    .map(([key, value]) => ({
      name: key,
      label: key.replace(/_/g, " ").toUpperCase(),
      value,
      color: VERDICT_COLORS[key] ?? FALLBACK_VERDICT_COLOR,
    }))
    .filter((d) => d.value > 0)
    .sort((a, b) => b.value - a.value)

  const avgConfidence = allJudge.length > 0
    ? allJudge.reduce((sum, e) => sum + e.confidence, 0) / allJudge.length
    : 0

  const pct = (n: number) => totalVerdicts > 0 ? `${((n / totalVerdicts) * 100).toFixed(0)}% of all` : "—"

  const proposalColumns = [
    {
      key: "id",
      header: "ID",
      render: (p: Proposal) => (
        <span className="text-muted-2">{p.proposal_id.slice(0, 8)}</span>
      ),
    },
    {
      key: "date",
      header: "Date",
      render: (p: Proposal) => <span>{formatDate(p.created_at)}</span>,
    },
    {
      key: "ticker",
      header: "Ticker",
      render: (p: Proposal) => <span className="font-semibold text-foreground">{p.ticker}</span>,
    },
    {
      key: "action",
      header: "Action",
      render: (p: Proposal) => (
        <Badge variant={p.action === "BUY" || p.action === "ADD" ? "profit" : "loss"}>{p.action}</Badge>
      ),
    },
    {
      key: "shares",
      header: "Shares",
      align: "right" as const,
      render: (p: Proposal) => <span>{p.shares}</span>,
    },
    {
      key: "status",
      header: "Status",
      render: (p: Proposal) => <Badge variant={statusVariant(p.status)}>{p.status}</Badge>,
    },
    {
      key: "human",
      header: "Human Decision",
      render: (p: Proposal) => (
        <span className="text-muted-2">{p.human_decision || "—"}</span>
      ),
    },
  ]

  const judgeColumns = [
    {
      key: "id",
      header: "ID",
      render: (e: JudgeLogEntry) => (
        <span className="text-muted-2">{e.log_id.slice(0, 8)}</span>
      ),
    },
    {
      key: "time",
      header: "Time",
      render: (e: JudgeLogEntry) => <span>{formatDateTime(e.created_at)}</span>,
    },
    {
      key: "target",
      header: "Target",
      render: (e: JudgeLogEntry) => (
        <span className="font-semibold text-foreground">{e.ticker}</span>
      ),
    },
    {
      key: "action",
      header: "Action",
      render: (e: JudgeLogEntry) => (
        <Badge variant={e.action === "BUY" || e.action === "ADD" ? "profit" : "loss"}>{e.action}</Badge>
      ),
    },
    {
      key: "verdict",
      header: "Verdict",
      render: (e: JudgeLogEntry) => (
        <Badge variant={verdictVariant(e.verdict)}>{e.verdict.toUpperCase()}</Badge>
      ),
    },
    {
      key: "confidence",
      header: "Confidence",
      align: "right" as const,
      render: (e: JudgeLogEntry) => <span>{e.confidence.toFixed(2)}</span>,
    },
    {
      key: "model",
      header: "Model",
      render: (e: JudgeLogEntry) => (
        <span className="text-muted-2">{e.model_used}</span>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Decision Log"
        description="Audit trail of every proposal and judge verdict"
      />

      <div className="grid grid-cols-4 gap-4 mb-[18px]">
        <MetricCard
          label="Approved"
          value={String(approvedCount)}
          sub={pct(approvedCount)}
        />
        <MetricCard
          label="Rejected"
          value={String(rejectedCount)}
          sub={pct(rejectedCount)}
        />
        <MetricCard
          label="Needs Review"
          value={String(reviewCount)}
          sub={pct(reviewCount)}
        />
        <MetricCard
          accent
          label="Avg Confidence"
          value={avgConfidence.toFixed(2)}
          sub="trailing 30d"
        />
      </div>

      <div className="grid gap-4 mb-4" style={{ gridTemplateColumns: "1fr 2fr" }}>
        <Card>
          <CardTitle meta={`${totalVerdicts} total`}>Judge Verdicts</CardTitle>
          <CardContent>
            {pieData.length > 0 ? (
              <div className="flex items-center gap-4">
                <div className="relative shrink-0" style={{ width: 150, height: 150 }}>
                  <ResponsiveContainer width={150} height={150}>
                    <PieChart>
                      <Pie
                        data={pieData}
                        cx="50%"
                        cy="50%"
                        innerRadius={42}
                        outerRadius={68}
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
                        formatter={(value, _name, item) => [`${value}`, (item?.payload as { label: string })?.label || ""]}
                        contentStyle={tooltipStyle}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                    <span className="font-mono text-[16px] font-medium tabular-nums text-foreground">
                      {totalVerdicts}
                    </span>
                  </div>
                </div>
                <div className="flex-1 font-mono text-[12px] space-y-0.5">
                  {pieData.map((d) => (
                    <div key={d.name} className="flex items-center gap-2 py-1">
                      <span
                        className="inline-block h-[10px] w-[10px] rounded-[2px]"
                        style={{ backgroundColor: d.color }}
                      />
                      <span className="flex-1 text-fg-dim">{d.label}</span>
                      <span className="tabular-nums text-foreground">{d.value}</span>
                      <span className="tabular-nums text-muted-2 min-w-[38px] text-right">
                        {totalVerdicts > 0 ? `${((d.value / totalVerdicts) * 100).toFixed(0)}%` : "—"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-12">No verdicts yet</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardTitle meta={`${allProposals.length} most recent`}>Proposals</CardTitle>
          <DataTable
            columns={proposalColumns}
            data={allProposals}
            rowKey={(p) => p.proposal_id}
            emptyMessage="No proposals logged yet."
            compact
          />
        </Card>
      </div>

      <Card>
        <CardTitle meta="LLM evaluation history">Judge Log</CardTitle>
        <DataTable
          columns={judgeColumns}
          data={allJudge}
          rowKey={(e) => e.log_id}
          emptyMessage="No judge decisions logged yet."
          compact
        />
      </Card>
    </>
  )
}
