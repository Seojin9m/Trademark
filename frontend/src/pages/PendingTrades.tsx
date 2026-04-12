import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { Proposal } from "@/lib/api"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { MetricCard } from "@/components/ui/metric-card"
import { Check, X, ChevronDown, ChevronUp, Clock, ShieldCheck } from "lucide-react"
import { cn } from "@/lib/utils"
import { useToast } from "@/contexts/toast-context"

function statusVariant(status: string): "profit" | "loss" | "warn" | "muted" | "default" {
  switch (status) {
    case "APPROVED":
    case "JUDGE_APPROVED":
    case "EXECUTED":
      return "profit"
    case "REJECTED":
    case "JUDGE_REJECTED":
      return "loss"
    case "PENDING":
    case "NEEDS_REVIEW":
      return "warn"
    case "NO_ACTION":
      return "muted"
    default:
      return "muted"
  }
}

function tryParseJson(val: unknown): Record<string, unknown> | null {
  if (typeof val === "object" && val !== null) return val as Record<string, unknown>
  if (typeof val === "string") {
    try { return JSON.parse(val) } catch { return null }
  }
  return null
}

function formatTimestamp(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })
  } catch {
    return ts
  }
}

function TradeCard({
  proposal,
  onApprove,
  onReject,
  approving,
  rejecting,
}: {
  proposal: Proposal
  onApprove: () => void
  onReject: () => void
  approving: boolean
  rejecting: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const signal = tryParseJson(proposal.signal_data)
  const judge = tryParseJson(proposal.judge_response)
  const canAct = ["PENDING", "JUDGE_APPROVED", "NEEDS_REVIEW"].includes(proposal.status)

  return (
    <div className="rounded-lg border border-border/40 bg-card/50 px-5 py-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span
            className={cn(
              "inline-flex h-9 w-9 items-center justify-center rounded-lg text-xs font-semibold",
              proposal.action === "BUY" || proposal.action === "ADD"
                ? "bg-profit/15 text-profit"
                : "bg-loss/15 text-loss",
            )}
          >
            {proposal.action}
          </span>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-base font-semibold">{proposal.ticker}</span>
              <span className="text-sm text-muted-foreground">
                {proposal.shares} shares
              </span>
            </div>
            {proposal.human_decision && (
              <p className="text-xs text-muted-foreground">{proposal.human_decision}</p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Badge variant={statusVariant(proposal.status)}>{proposal.status}</Badge>
          {canAct && (
            <div className="flex gap-1.5">
              <Button
                size="sm"
                onClick={onApprove}
                disabled={approving}
              >
                <Check className="h-3.5 w-3.5 mr-1" />
                Approve
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={onReject}
                disabled={rejecting}
              >
                <X className="h-3.5 w-3.5 mr-1" />
                Reject
              </Button>
            </div>
          )}
        </div>
      </div>

      {(signal || judge) && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-3 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {expanded ? "Hide details" : "Show details"}
        </button>
      )}

      {expanded && (
        <div className="mt-3 space-y-3">
          {signal && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
                Signal Data
              </p>
              <div className="rounded-lg bg-muted/50 border border-border/40 p-3 text-xs font-mono overflow-x-auto">
                <pre className="text-muted-foreground">{JSON.stringify(signal, null, 2)}</pre>
              </div>
            </div>
          )}
          {judge && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
                Judge Response
              </p>
              <div className="rounded-lg bg-muted/50 border border-border/40 p-3 text-xs font-mono overflow-x-auto">
                <pre className="text-muted-foreground">{JSON.stringify(judge, null, 2)}</pre>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function StayCard({ proposal }: { proposal: Proposal }) {
  const [expanded, setExpanded] = useState(false)
  const judge = tryParseJson(proposal.judge_response)
  const assessment = judge?.market_assessment as string | undefined
  const confidence = judge?.confidence as number | undefined
  const verdict = judge?.overall_verdict as string | undefined

  return (
    <div className="rounded-lg border border-border/40 bg-card/50 px-5 py-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500/15 text-blue-400">
            <ShieldCheck className="h-5 w-5" />
          </span>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-base font-semibold">No Trades</span>
              <span className="text-sm text-muted-foreground">Pipeline declared HOLD</span>
            </div>
            {assessment && (
              <p className="text-xs text-muted-foreground mt-0.5 max-w-xl">{assessment}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {verdict && (
            <Badge variant={verdict === "agree" ? "muted" : "warn"}>
              Judge {verdict === "agree" ? "agrees" : "disagrees"}
              {confidence != null ? ` (${(confidence * 100).toFixed(0)}%)` : ""}
            </Badge>
          )}
          <Badge variant="default" className="bg-blue-500/20 text-blue-400 border-blue-500/30">
            HOLD
          </Badge>
        </div>
      </div>

      {judge && (
        <>
          <button
            onClick={() => setExpanded(!expanded)}
            className="mt-3 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            {expanded ? "Hide review" : "Show portfolio review"}
          </button>

          {expanded && (
            <div className="mt-3">
              <div className="rounded-lg bg-muted/50 border border-border/40 p-3 text-xs font-mono overflow-x-auto">
                <pre className="text-muted-foreground">{JSON.stringify(judge, null, 2)}</pre>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

interface RunGroup {
  run_id: string
  timestamp: string
  proposals: Proposal[]
}

function groupByRun(proposals: Proposal[]): RunGroup[] {
  const groups = new Map<string, Proposal[]>()
  for (const p of proposals) {
    const key = p.run_id || "unknown"
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(p)
  }
  // Sort groups by most recent proposal timestamp
  return Array.from(groups.entries())
    .map(([run_id, proposals]) => ({
      run_id,
      timestamp: proposals[0]?.created_at || "",
      proposals,
    }))
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
}

export default function PendingTrades() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [filter, setFilter] = useState("All")
  const { data: proposals, isLoading } = useQuery<Proposal[]>({
    queryKey: ["proposals"],
    queryFn: () => api.getProposals(undefined, 100),
  })

  const approveMut = useMutation({
    mutationFn: (id: string) => api.approveProposal(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["proposals"] })
      toast("success", "Trade Approved")
    },
    onError: (e) => toast("error", "Approve Failed", String(e)),
  })

  const rejectMut = useMutation({
    mutationFn: (id: string) => api.rejectProposal(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["proposals"] })
      toast("info", "Trade Rejected")
    },
    onError: (e) => toast("error", "Reject Failed", String(e)),
  })

  if (isLoading) {
    return (
      <>
        <PageHeader title="Pending Trades" />
        <div className="space-y-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-24 rounded-xl border border-border/60 bg-card animate-shimmer" />
          ))}
        </div>
      </>
    )
  }

  const all = proposals || []
  const statuses = ["All", ...Array.from(new Set(all.map((p) => p.status)))]
  const filtered = filter === "All" ? all : all.filter((p) => p.status === filter)
  const runGroups = groupByRun(filtered)

  const pending = all.filter((p) => ["PENDING", "NEEDS_REVIEW"].includes(p.status)).length
  const approved = all.filter((p) => ["APPROVED", "JUDGE_APPROVED"].includes(p.status)).length
  const executed = all.filter((p) => p.status === "EXECUTED").length
  const rejected = all.filter((p) => ["REJECTED", "JUDGE_REJECTED"].includes(p.status)).length

  return (
    <>
      <PageHeader title="Trades" description={`${all.length} total proposals`} />

      <div className="grid grid-cols-4 gap-4 mb-6">
        <MetricCard label="Pending Review" value={String(pending)} />
        <MetricCard label="Approved" value={String(approved)} />
        <MetricCard label="Executed" value={String(executed)} />
        <MetricCard label="Rejected" value={String(rejected)} />
      </div>

      <div className="flex gap-2 mb-6">
        {statuses.map((s) => (
          <Button
            key={s}
            variant={filter === s ? "default" : "outline"}
            size="sm"
            onClick={() => setFilter(s)}
          >
            {s}
          </Button>
        ))}
      </div>

      {runGroups.length === 0 ? (
        <Card>
          <CardContent>
            <p className="text-sm text-muted-foreground py-12 text-center">
              No trade proposals. Run the pipeline to generate signals.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          {runGroups.map((group) => (
            <Card key={group.run_id}>
              <div className="px-6 pt-4 pb-2 border-b border-border/40">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <Clock className="h-4 w-4 text-muted-foreground" />
                    <span className="text-sm font-medium">
                      Pipeline Run{" "}
                      <span className="font-mono text-muted-foreground">
                        {group.run_id === "unknown" ? "—" : group.run_id}
                      </span>
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-muted-foreground">
                      {formatTimestamp(group.timestamp)}
                    </span>
                    <Badge variant="muted">
                      {(() => {
                        const trades = group.proposals.filter((p) => p.action !== "STAY")
                        if (trades.length === 0) return "hold"
                        return `${trades.length} trade${trades.length !== 1 ? "s" : ""}`
                      })()}
                    </Badge>
                  </div>
                </div>
              </div>
              <CardContent>
                <div className="space-y-2 pt-2">
                  {group.proposals.map((p) =>
                    p.action === "STAY" ? (
                      <StayCard key={p.proposal_id} proposal={p} />
                    ) : (
                      <TradeCard
                        key={p.proposal_id}
                        proposal={p}
                        onApprove={() => approveMut.mutate(p.proposal_id)}
                        onReject={() => rejectMut.mutate(p.proposal_id)}
                        approving={approveMut.isPending}
                        rejecting={rejectMut.isPending}
                      />
                    ),
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </>
  )
}
