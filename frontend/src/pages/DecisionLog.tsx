import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { Proposal, JudgeLogEntry } from "@/lib/api"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { DataTable } from "@/components/ui/data-table"
import { MetricCard } from "@/components/ui/metric-card"
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts"

const VERDICT_COLORS: Record<string, string> = {
  approve: "#22c55e",
  reject: "#ef4444",
  needs_review: "#f59e0b",
}

const tooltipStyle = {
  backgroundColor: "#111113",
  border: "1px solid #1f1f2e",
  borderRadius: "0.75rem",
  color: "#fafafa",
  fontSize: "12px",
  boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
}

export default function DecisionLog() {
  const { data: proposals, isLoading: loadingProposals } = useQuery<Proposal[]>({
    queryKey: ["proposals-log"],
    queryFn: () => api.getProposals(undefined, 100),
  })

  const { data: judgeLog, isLoading: loadingJudge } = useQuery<JudgeLogEntry[]>({
    queryKey: ["judge-log"],
    queryFn: () => api.getJudgeLog(50),
  })

  if (loadingProposals || loadingJudge) {
    return (
      <>
        <PageHeader title="Decision Log" />
        <div className="space-y-6">
          {[0, 1].map((i) => (
            <div key={i} className="h-48 rounded-xl border border-border/60 bg-card animate-shimmer" />
          ))}
        </div>
      </>
    )
  }

  const allProposals = proposals || []
  const allJudge = judgeLog || []

  const verdictCounts = allJudge.reduce<Record<string, number>>((acc, e) => {
    acc[e.verdict] = (acc[e.verdict] || 0) + 1
    return acc
  }, {})
  const pieData = Object.entries(verdictCounts).map(([name, value]) => ({ name, value }))
  const avgConfidence = allJudge.length > 0
    ? allJudge.reduce((sum, e) => sum + e.confidence, 0) / allJudge.length
    : 0

  const proposalColumns = [
    {
      key: "id",
      header: "ID",
      render: (p: Proposal) => (
        <span className="text-xs text-muted-foreground">{p.proposal_id.slice(0, 8)}</span>
      ),
    },
    {
      key: "date",
      header: "Date",
      render: (p: Proposal) => <span className="text-xs">{p.created_at}</span>,
    },
    {
      key: "ticker",
      header: "Ticker",
      render: (p: Proposal) => <span className="font-semibold">{p.ticker}</span>,
    },
    {
      key: "action",
      header: "Action",
      render: (p: Proposal) => (
        <Badge variant={p.action === "BUY" ? "profit" : "loss"}>{p.action}</Badge>
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
      render: (p: Proposal) => <Badge variant="muted">{p.status}</Badge>,
    },
    {
      key: "human",
      header: "Human",
      render: (p: Proposal) => (
        <span className="text-xs text-muted-foreground">{p.human_decision || "-"}</span>
      ),
    },
  ]

  const judgeColumns = [
    {
      key: "date",
      header: "Date",
      render: (e: JudgeLogEntry) => <span className="text-xs">{e.created_at}</span>,
    },
    {
      key: "ticker",
      header: "Ticker",
      render: (e: JudgeLogEntry) => <span className="font-semibold">{e.ticker}</span>,
    },
    {
      key: "action",
      header: "Action",
      render: (e: JudgeLogEntry) => (
        <Badge variant={e.action === "BUY" ? "profit" : "loss"}>{e.action}</Badge>
      ),
    },
    {
      key: "verdict",
      header: "Verdict",
      render: (e: JudgeLogEntry) => (
        <Badge variant={e.verdict === "approve" ? "profit" : e.verdict === "reject" ? "loss" : "warn"}>
          {e.verdict}
        </Badge>
      ),
    },
    {
      key: "confidence",
      header: "Confidence",
      align: "right" as const,
      render: (e: JudgeLogEntry) => (
        <span>{(e.confidence * 100).toFixed(0)}%</span>
      ),
    },
    {
      key: "model",
      header: "Model",
      render: (e: JudgeLogEntry) => (
        <span className="text-xs text-muted-foreground">{e.model_used}</span>
      ),
    },
  ]

  return (
    <>
      <PageHeader title="Decision Log" description="All proposals and judge decisions" />

      <div className="grid grid-cols-4 gap-4 mb-6">
        <MetricCard label="Total Proposals" value={String(allProposals.length)} />
        <MetricCard label="Judge Decisions" value={String(allJudge.length)} />
        <MetricCard
          label="Avg Confidence"
          value={`${(avgConfidence * 100).toFixed(0)}%`}
        />
        <MetricCard label="Approval Rate" value={
          allJudge.length > 0
            ? `${((verdictCounts["approve"] || 0) / allJudge.length * 100).toFixed(0)}%`
            : "N/A"
        } />
      </div>

      <Card className="mb-6">
        <CardTitle>Trade Proposals</CardTitle>
        <CardContent>
          <DataTable
            columns={proposalColumns}
            data={allProposals}
            rowKey={(p) => p.proposal_id}
            emptyMessage="No proposals logged yet."
            compact
          />
        </CardContent>
      </Card>

      <div className="grid grid-cols-3 gap-6">
        <Card className="col-span-2">
          <CardTitle>LLM Judge Log</CardTitle>
          <CardContent>
            <DataTable
              columns={judgeColumns}
              data={allJudge}
              rowKey={(e) => e.log_id}
              emptyMessage="No judge decisions logged yet."
              compact
            />
          </CardContent>
        </Card>

        <Card>
          <CardTitle>Verdict Distribution</CardTitle>
          <CardContent>
            {pieData.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={220}>
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
                        <Cell key={d.name} fill={VERDICT_COLORS[d.name] || "#a1a1aa"} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={tooltipStyle} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="mt-3 space-y-2">
                  {pieData.map((d) => (
                    <div key={d.name} className="flex items-center justify-between text-sm">
                      <div className="flex items-center gap-2.5">
                        <span
                          className="inline-block h-2.5 w-2.5 rounded-full"
                          style={{ backgroundColor: VERDICT_COLORS[d.name] || "#a1a1aa" }}
                        />
                        <span className="text-muted-foreground capitalize">{d.name}</span>
                      </div>
                      <span className="font-medium">{d.value}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-12">No data yet</p>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  )
}
