import { useState, useEffect, useRef } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { Proposal } from "@/lib/api"
import { usePipeline } from "@/contexts/pipeline-context"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { MetricCard } from "@/components/ui/metric-card"
import { Check, X, ChevronDown, ChevronUp, Clock, ShieldCheck, Sparkles, Trash2 } from "lucide-react"
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
      const avgLen = value.reduce((s, v) => s + String(v).length, 0) / value.length
      if (avgLen > 40) {
        return null
      }
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

  const isLongStringArray =
    Array.isArray(value) &&
    value.length > 0 &&
    value.every((v) => typeof v === "string") &&
    (value as string[]).reduce((s, v) => s + v.length, 0) / value.length > 40

  if (isLongStringArray) {
    return (
      <div className="space-y-2">
        <p className="text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">
          {label}
        </p>
        <div className="space-y-1.5">
          {(value as string[]).map((item, i) => {
            const dashIdx = item.indexOf(" — ")
            const headline = dashIdx > -1 ? item.slice(0, dashIdx) : null
            const detail = dashIdx > -1 ? item.slice(dashIdx + 3) : item
            return (
              <div key={i} className="rounded-lg border border-border/40 bg-background/40 px-3 py-2">
                <div className="flex items-start gap-2">
                  <span className="text-muted-foreground/50 mt-0.5 shrink-0 text-xs">•</span>
                  <div className="min-w-0">
                    {headline && (
                      <p className="text-sm font-medium text-foreground mb-0.5">{headline}</p>
                    )}
                    <p className="text-sm text-foreground/70 leading-relaxed">{detail}</p>
                  </div>
                </div>
              </div>
            )
          })}
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
  const constraint = tryParseJson(proposal.constraint_check)
  const canAct = ["PENDING", "JUDGE_APPROVED", "NEEDS_REVIEW"].includes(proposal.status)

  // Identify the proposal's origin — the regular pipeline writes full factor
  // data, the judge-override path writes a stub signal_data with source =
  // "judge_review". That distinction drives the empty-state copy for the
  // Judge Response block so the user isn't left wondering why it's missing.
  const isJudgeOriginated =
    typeof signal?.source === "string" && signal.source === "judge_review"
  const violations = Array.isArray(constraint?.violations)
    ? (constraint!.violations as unknown[]).filter(
        (v): v is string => typeof v === "string",
      )
    : []
  const constraintBlocked =
    constraint?.passed === false || violations.length > 0
  const signalHasContent = signal && Object.keys(signal).length > 0
  const judgeHasContent = judge && Object.keys(judge).length > 0

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
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-base font-semibold">{proposal.ticker}</span>
              <span className="text-sm text-muted-foreground">
                {proposal.shares} shares
              </span>
            </div>
            {proposal.reason && (
              <p className="text-xs text-muted-foreground mt-0.5 max-w-2xl truncate">
                {proposal.reason}
              </p>
            )}
            {proposal.human_decision && (
              <p className="text-xs text-muted-foreground/60 mt-0.5">{proposal.human_decision}</p>
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

      <button
        onClick={() => setExpanded(!expanded)}
        className="mt-3 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        {expanded ? "Hide details" : "Show details"}
      </button>

      {expanded && (
        <div className="mt-3 space-y-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
              Signal Data
            </p>
            <div className="rounded-lg bg-muted/40 border border-border/40 px-4 py-3 space-y-3">
              {signalHasContent ? (
                <DetailList data={signal!} />
              ) : (
                <p className="text-xs text-muted-foreground italic">
                  No signal data — this proposal was created directly by the
                  judge's portfolio review, not by the factor pipeline.
                </p>
              )}
              {constraintBlocked && (
                <div className="rounded-md border border-loss/30 bg-loss/10 px-3 py-2">
                  <p className="text-[10.5px] font-semibold uppercase tracking-wider text-loss mb-1.5">
                    Blocked by Constraints
                  </p>
                  <ul className="space-y-1 text-xs text-foreground/90">
                    {violations.map((v, i) => (
                      <li key={i} className="flex gap-1.5">
                        <span className="text-loss">•</span>
                        <span>{v}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
              Judge Response
            </p>
            <div className="rounded-lg bg-muted/40 border border-border/40 px-4 py-3">
              {judgeHasContent ? (
                <DetailList data={judge!} />
              ) : (
                <p className="text-xs text-muted-foreground italic">
                  {constraintBlocked
                    ? "Not evaluated — constraint check failed before the judge could run."
                    : isJudgeOriginated
                      ? "No per-proposal verdict — this trade was initiated by the judge during a portfolio review, so its reasoning is in the Signal Data above."
                      : "Judge verdict not available for this proposal."}
                </p>
              )}
            </div>
          </div>
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

function buildRunSummary(proposals: Proposal[]): string {
  const trades = proposals.filter((p) => p.action !== "STAY")
  if (trades.length === 0) return "No trades proposed — holding all positions."

  const counts: Record<string, number> = {}
  for (const t of trades) {
    counts[t.action] = (counts[t.action] || 0) + 1
  }

  const parts: string[] = []
  if (counts.BUY) parts.push(`${counts.BUY} buy${counts.BUY > 1 ? "s" : ""}`)
  if (counts.ADD) parts.push(`${counts.ADD} add${counts.ADD > 1 ? "s" : ""}`)
  if (counts.TRIM) parts.push(`${counts.TRIM} trim${counts.TRIM > 1 ? "s" : ""}`)
  if (counts.SELL) parts.push(`${counts.SELL} sell${counts.SELL > 1 ? "s" : ""}`)

  const tickers = trades.map((t) => t.ticker)
  const unique = [...new Set(tickers)]
  return `${parts.join(", ")} across ${unique.length} stock${unique.length > 1 ? "s" : ""} (${unique.join(", ")})`
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
  const { lastCompletedRunId, clearLastCompletedRunId } = usePipeline()
  const [filter, setFilter] = useState("All")
  const highlightRef = useRef<HTMLDivElement>(null)
  const { data: proposals, isLoading } = useQuery<Proposal[]>({
    queryKey: ["proposals"],
    queryFn: () => api.getProposals(undefined, 100),
  })

  useEffect(() => {
    if (lastCompletedRunId && highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }, [lastCompletedRunId, proposals])

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

  const [menuOpenRunId, setMenuOpenRunId] = useState<string | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpenRunId(null)
      }
    }
    if (menuOpenRunId) document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [menuOpenRunId])

  const deleteRunMut = useMutation({
    mutationFn: (runId: string) => api.deleteRun(runId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["proposals"] })
      toast("success", "Run Deleted", `Removed ${data.deleted_count} proposal${data.deleted_count !== 1 ? "s" : ""}`)
      setMenuOpenRunId(null)
    },
    onError: (e) => {
      toast("error", "Delete Failed", String(e))
      setMenuOpenRunId(null)
    },
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
          {runGroups.map((group) => {
            const isLatestRun = lastCompletedRunId && group.run_id === lastCompletedRunId
            return (
            <Card
              key={group.run_id}
              ref={isLatestRun ? highlightRef : undefined}
              className={cn(isLatestRun && "ring-2 ring-primary/50 shadow-lg shadow-primary/10")}
            >
              <div className={cn(
                "px-6 pt-4 pb-3 border-b border-border/40",
                isLatestRun && "bg-primary/[0.03]",
              )}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    {isLatestRun ? (
                      <Sparkles className="h-4 w-4 text-primary" />
                    ) : (
                      <Clock className="h-4 w-4 text-muted-foreground" />
                    )}
                    <span className="text-sm font-medium">
                      Pipeline Run{" "}
                      <span className="font-mono text-muted-foreground">
                        {group.run_id === "unknown" ? "—" : group.run_id}
                      </span>
                    </span>
                    {isLatestRun && (
                      <Badge variant="default" className="bg-primary/20 text-primary border-primary/30 text-[10px]">
                        LATEST
                      </Badge>
                    )}
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
                    {isLatestRun && (
                      <button
                        onClick={clearLastCompletedRunId}
                        className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                        title="Dismiss highlight"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    )}
                    {group.run_id !== "unknown" && (
                      <div className="relative" ref={menuOpenRunId === group.run_id ? menuRef : undefined}>
                        <button
                          onClick={() => setMenuOpenRunId(menuOpenRunId === group.run_id ? null : group.run_id)}
                          className="p-1.5 rounded-md text-muted-foreground/40 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                          title="Delete this pipeline run"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                        {menuOpenRunId === group.run_id && (
                          <div className="absolute right-0 top-full mt-1 z-50 w-40 rounded-lg border border-border/60 bg-card shadow-xl shadow-black/40 py-1">
                            <button
                              onClick={() => deleteRunMut.mutate(group.run_id)}
                              disabled={deleteRunMut.isPending}
                              className="w-full flex items-center gap-2 px-3 py-2 text-xs text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                              {deleteRunMut.isPending ? "Deleting..." : "Delete run"}
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
                <p className="text-xs text-muted-foreground mt-1.5">
                  {buildRunSummary(group.proposals)}
                </p>
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
            )
          })}
        </div>
      )}
    </>
  )
}
