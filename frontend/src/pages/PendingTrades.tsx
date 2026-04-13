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

// ─── Pretty detail renderer ─────────────────────────────────────────────────
// Turns signal/judge JSON payloads into human-readable key/value rows. Long
// prose fields get their own wrapped block; numbers in 0..1 against known
// percent-y keys render as percentages; identifier-ish keys render as badges.

const PROSE_KEYS = new Set([
  "reason",
  "rationale",
  "explanation",
  "notes",
  "summary",
  "market_assessment",
  "analysis",
  "commentary",
  "thesis",
  "recommendation",
])

const BADGE_KEYS = new Set([
  "source",
  "overall_verdict",
  "verdict",
  "action",
  "status",
  "regime",
])

// Keys that are z-scores, not 0..1 probabilities. Our factor pipeline outputs
// standardized factor values (~-3..+3) and a weighted-average composite_score
// on the same scale — rendering them as "85%" (the old behavior) was wrong
// and actively misleading.
const FACTOR_KEYS = new Set([
  "momentum_12m1m",
  "eps_growth_yoy",
  "revenue_growth_yoy",
  "gross_margin_trend",
  "relative_valuation",
])

const ZSCORE_KEYS = new Set([...FACTOR_KEYS, "composite_score"])

function isPercentKey(key: string): boolean {
  const k = key.toLowerCase()
  if (ZSCORE_KEYS.has(k)) return false
  return (
    k === "conviction" ||
    k === "confidence" ||
    k.endsWith("_score") ||
    k.endsWith("_probability") ||
    k.endsWith("_pct") ||
    k.endsWith("_ratio")
  )
}

// Map a z-score to a qualitative label. Thresholds are loose — the intent is
// to give a retail reader a quick "is this strong or weak" read without them
// having to translate standard deviations in their head.
function zScoreLabel(z: number): { label: string; className: string } {
  if (z >= 1.25) return { label: "Very strong", className: "text-profit" }
  if (z >= 0.5) return { label: "Strong", className: "text-profit" }
  if (z > -0.5) return { label: "Neutral", className: "text-muted-foreground" }
  if (z > -1.25) return { label: "Weak", className: "text-warn" }
  return { label: "Very weak", className: "text-loss" }
}

function prettifyKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function percentColorClass(pct: number): string {
  if (pct >= 0.75) return "text-profit"
  if (pct >= 0.5) return "text-warn"
  return "text-loss"
}

function actionBadgeClasses(action: string): string {
  const a = action.toUpperCase()
  if (a === "BUY" || a === "ADD" || a === "LONG") {
    return "bg-profit/15 text-profit border-profit/30"
  }
  if (a === "SELL" || a === "TRIM" || a === "EXIT" || a === "SHORT") {
    return "bg-loss/15 text-loss border-loss/30"
  }
  if (a === "HOLD" || a === "STAY") {
    return "bg-blue-500/15 text-blue-400 border-blue-500/30"
  }
  return ""
}

function formatInlineValue(value: unknown, key: string): React.ReactNode {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground italic">—</span>
  }
  if (typeof value === "boolean") {
    return (
      <Badge variant={value ? "profit" : "muted"} className="font-normal">
        {value ? "Yes" : "No"}
      </Badge>
    )
  }
  if (typeof value === "number") {
    const keyLower = key.toLowerCase()
    if (ZSCORE_KEYS.has(keyLower)) {
      const { label, className } = zScoreLabel(value)
      return (
        <span className="inline-flex items-baseline gap-1.5">
          <span className={cn("font-semibold", className)}>{label}</span>
          <span className="text-[11px] text-muted-foreground tabular-nums">
            ({value >= 0 ? "+" : ""}
            {value.toFixed(2)}σ)
          </span>
        </span>
      )
    }
    if (keyLower === "score_decile" || keyLower === "decile") {
      const d = Math.round(value)
      const cls =
        d >= 8 ? "text-profit" : d >= 5 ? "text-warn" : "text-loss"
      return (
        <span className={cn("font-semibold tabular-nums", cls)}>
          {d} / 10
        </span>
      )
    }
    if (isPercentKey(key) && value >= 0 && value <= 1) {
      return (
        <span className={cn("font-semibold tabular-nums", percentColorClass(value))}>
          {(value * 100).toFixed(0)}%
        </span>
      )
    }
    if (Number.isInteger(value)) {
      return <span className="font-medium tabular-nums">{value.toLocaleString()}</span>
    }
    return <span className="font-medium tabular-nums">{value.toFixed(4)}</span>
  }
  if (typeof value === "string") {
    if (BADGE_KEYS.has(key.toLowerCase())) {
      const k = key.toLowerCase()
      const isActionLike = k === "action" || k === "recommendation"
      return (
        <Badge
          variant="muted"
          className={cn("font-normal", isActionLike && actionBadgeClasses(value))}
        >
          {value}
        </Badge>
      )
    }
    return <span className="text-foreground">{value}</span>
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="text-muted-foreground italic">empty</span>
    }
    if (value.every((v) => typeof v === "string" || typeof v === "number")) {
      return (
        <div className="flex flex-wrap justify-end gap-1">
          {value.map((v, i) => (
            <Badge key={i} variant="muted" className="font-normal">
              {String(v)}
            </Badge>
          ))}
        </div>
      )
    }
  }
  return null
}

function DetailField({ fieldKey, value }: { fieldKey: string; value: unknown }) {
  const label = prettifyKey(fieldKey)
  const keyLower = fieldKey.toLowerCase()

  const isProse =
    typeof value === "string" &&
    (PROSE_KEYS.has(keyLower) || value.length > 80)

  const isNestedObject =
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)

  const isComplexArray =
    Array.isArray(value) &&
    value.length > 0 &&
    !value.every((v) => typeof v === "string" || typeof v === "number")

  if (isProse) {
    return (
      <div className="space-y-1">
        <p className="text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">
          {label}
        </p>
        <p className="text-sm text-foreground/90 leading-relaxed whitespace-pre-wrap">
          {value as string}
        </p>
      </div>
    )
  }

  if (isNestedObject) {
    return (
      <div className="space-y-1.5">
        <p className="text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">
          {label}
        </p>
        <div className="border-l-2 border-border/50 pl-3">
          <DetailList data={value as Record<string, unknown>} />
        </div>
      </div>
    )
  }

  if (isComplexArray) {
    return (
      <div className="space-y-2">
        <p className="text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">
          {label}
        </p>
        <div className="space-y-2.5">
          {(value as unknown[]).map((item, i) => (
            <NestedItemCard key={i} item={item} />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-start justify-between gap-4 py-0.5">
      <span className="text-xs text-muted-foreground pt-0.5 shrink-0">
        {label}
      </span>
      <div className="text-sm text-right min-w-0 break-words">
        {formatInlineValue(value, fieldKey)}
      </div>
    </div>
  )
}

// Array items (e.g. holdings_review entries) get their own card with the
// ticker / name pulled out as a header so it's obvious which rows belong to
// which item.
function NestedItemCard({ item }: { item: unknown }) {
  if (typeof item !== "object" || item === null || Array.isArray(item)) {
    return (
      <div className="rounded-md bg-background/50 border border-border/50 px-3 py-2 text-sm">
        {String(item)}
      </div>
    )
  }

  const obj = item as Record<string, unknown>
  const headlineKey = ["ticker", "symbol", "name", "id"].find(
    (k) => typeof obj[k] === "string" && (obj[k] as string).length > 0,
  )
  const headline = headlineKey ? (obj[headlineKey] as string) : null

  // Pull an action/verdict field out as a small subtitle badge if present
  const subtitleKey = ["action", "verdict", "status", "recommendation"].find(
    (k) => typeof obj[k] === "string",
  )
  const subtitle = subtitleKey ? (obj[subtitleKey] as string) : null

  const rest = Object.fromEntries(
    Object.entries(obj).filter(
      ([k]) => k !== headlineKey && k !== subtitleKey,
    ),
  )

  return (
    <div className="rounded-lg bg-background/50 border border-border/60 overflow-hidden">
      {headline && (
        <div className="flex items-center justify-between gap-3 px-3.5 py-2 border-b border-border/40 bg-background/60">
          <span className="text-sm font-semibold tracking-tight">
            {headline}
          </span>
          {subtitle && (
            <Badge
              variant="muted"
              className={cn(
                "font-normal uppercase tracking-wide text-[10px]",
                actionBadgeClasses(subtitle),
              )}
            >
              {subtitle}
            </Badge>
          )}
        </div>
      )}
      <div className="px-3.5 py-2.5">
        <DetailList data={rest} />
      </div>
    </div>
  )
}

function DetailList({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data)
  if (entries.length === 0) {
    return <p className="text-xs text-muted-foreground italic">No details</p>
  }
  return (
    <div className="space-y-2.5">
      {entries.map(([key, value]) => (
        <DetailField key={key} fieldKey={key} value={value} />
      ))}
    </div>
  )
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
        <div className="mt-3 space-y-4">
          {signal && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                Signal Data
              </p>
              <div className="rounded-lg bg-muted/40 border border-border/40 px-4 py-3">
                <DetailList data={signal} />
              </div>
            </div>
          )}
          {judge && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                Judge Response
              </p>
              <div className="rounded-lg bg-muted/40 border border-border/40 px-4 py-3">
                <DetailList data={judge} />
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
              <div className="rounded-lg bg-muted/40 border border-border/40 px-4 py-3">
                <DetailList data={judge} />
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
