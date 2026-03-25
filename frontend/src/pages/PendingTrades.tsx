import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { Proposal } from "@/lib/api"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { DataTable } from "@/components/ui/data-table"
import { MetricCard } from "@/components/ui/metric-card"
import { Check, X, ChevronDown, ChevronUp } from "lucide-react"
import { cn } from "@/lib/utils"
import { useToast } from "@/contexts/toast-context"

function statusVariant(status: string): "profit" | "loss" | "warn" | "muted" | "default" {
  switch (status) {
    case "APPROVED":
    case "JUDGE_APPROVED":
      return "profit"
    case "REJECTED":
    case "JUDGE_REJECTED":
      return "loss"
    case "PENDING":
    case "NEEDS_REVIEW":
      return "warn"
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
    <Card>
      <div className="px-6 pt-5 pb-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span
              className={cn(
                "inline-flex h-9 w-9 items-center justify-center rounded-lg text-xs font-semibold",
                proposal.action === "BUY"
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
              <p className="text-xs text-muted-foreground">{proposal.created_at}</p>
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
    </Card>
  )
}

export default function PendingTrades() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [filter, setFilter] = useState("All")
  const { data: proposals, isLoading } = useQuery<Proposal[]>({
    queryKey: ["proposals"],
    queryFn: () => api.getProposals(undefined, 50),
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
  const statuses = ["All", ...new Set(all.map((p) => p.status))]
  const filtered = filter === "All" ? all : all.filter((p) => p.status === filter)

  const pending = all.filter((p) => ["PENDING", "NEEDS_REVIEW"].includes(p.status)).length
  const approved = all.filter((p) => ["APPROVED", "JUDGE_APPROVED"].includes(p.status)).length
  const rejected = all.filter((p) => ["REJECTED", "JUDGE_REJECTED"].includes(p.status)).length

  return (
    <>
      <PageHeader title="Pending Trades" description={`${all.length} total proposals`} />

      <div className="grid grid-cols-3 gap-4 mb-6">
        <MetricCard label="Pending Review" value={String(pending)} />
        <MetricCard label="Approved" value={String(approved)} />
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

      {filtered.length === 0 ? (
        <Card>
          <CardContent>
            <p className="text-sm text-muted-foreground py-12 text-center">
              No trade proposals. Run the pipeline to generate signals.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {filtered.map((p) => (
            <TradeCard
              key={p.proposal_id}
              proposal={p}
              onApprove={() => approveMut.mutate(p.proposal_id)}
              onReject={() => rejectMut.mutate(p.proposal_id)}
              approving={approveMut.isPending}
              rejecting={rejectMut.isPending}
            />
          ))}
        </div>
      )}
    </>
  )
}
