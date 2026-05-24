import { useState, useEffect, useRef } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { Proposal } from "@/lib/api"
import { usePipeline } from "@/contexts/pipeline-context"
import { PageHeader } from "@/components/layout/page-header"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { MetricCard } from "@/components/ui/metric-card"
import { Check, X, ChevronDown, ChevronRight, ShieldAlert, Trash2, ArrowUp, ArrowDown } from "lucide-react"
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
    return "bg-info/15 text-info border-info/30"
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

  const isBuy = proposal.action === "BUY" || proposal.action === "ADD"

  // Detect budget-impacted proposals from the violations list (string match —
  // the wording comes from build_trade_proposals._make_proposal).
  const budgetExhausted = violations.some((v) =>
    v.startsWith("Budget exhausted") || v.startsWith("Budget too small"),
  )
  const autoShrunk = violations.some((v) => v.startsWith("Auto-shrunk"))

  // Pull the dollar cost off the typed payload — signal_data has it when the
  // proposal came through build_trade_proposals (which it does for everything
  // except direct judge overrides). Fall back to undefined so we render "—".
  const estValue =
    typeof (signal as { estimated_value?: number } | null)?.estimated_value === "number"
      ? (signal as { estimated_value?: number }).estimated_value
      : (proposal as unknown as { estimated_value?: number }).estimated_value
  const costLabel =
    typeof estValue === "number" && estValue > 0
      ? `$${Math.round(estValue).toLocaleString()}`
      : null

  return (
    <div
      className={cn(
        "border-b border-line last:border-b-0",
        budgetExhausted && "opacity-50",
      )}
    >
      <div
        className="grid items-center gap-[14px] px-4 py-[14px]"
        style={{ gridTemplateColumns: "70px 110px 1fr auto auto" }}
      >
        <Badge variant={isBuy ? "profit" : "loss"}>
          {isBuy ? <ArrowUp className="h-2.5 w-2.5" /> : <ArrowDown className="h-2.5 w-2.5" />}
          {proposal.action}
        </Badge>

        <div>
          <div className="font-mono text-[15px] font-semibold text-foreground leading-tight">
            {proposal.ticker}
          </div>
          <div className="font-mono text-[10px] text-muted-foreground">
            {proposal.shares} shares{costLabel && <> · {costLabel}</>}
          </div>
          {autoShrunk && (
            <div
              className="font-mono text-[9.5px] uppercase tracking-[0.08em] text-warn mt-0.5"
              title={violations.find((v) => v.startsWith("Auto-shrunk"))}
            >
              ↘ AUTO-SHRUNK
            </div>
          )}
          {budgetExhausted && (
            <div
              className="font-mono text-[9.5px] uppercase tracking-[0.08em] text-loss mt-0.5"
              title={violations.find((v) => v.startsWith("Budget")) ?? ""}
            >
              ⊘ BUDGET EXHAUSTED
            </div>
          )}
        </div>

        <div className="text-[12px] leading-[1.5] text-fg-dim min-w-0">
          {proposal.reason || <span className="text-muted-2 italic">No reason provided</span>}
          {proposal.human_decision && (
            <div className="text-[11px] text-muted-2 mt-0.5">{proposal.human_decision}</div>
          )}
        </div>

        <Badge variant={statusVariant(proposal.status)}>{proposal.status}</Badge>

        <div className="flex items-center gap-1.5">
          {canAct && (
            <>
              <Button size="sm" variant="primary" onClick={onApprove} disabled={approving}>
                <Check className="h-3 w-3" />
                Approve
              </Button>
              <Button size="sm" variant="destructive" onClick={onReject} disabled={rejecting}>
                <X className="h-3 w-3" />
                Reject
              </Button>
            </>
          )}
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center justify-center h-[24px] w-[24px] rounded-[4px] text-muted-foreground hover:bg-surface-2 hover:text-foreground transition-colors"
            title={expanded ? "Hide details" : "Show details"}
          >
            {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="px-4 pt-2 pb-[18px] bg-bg-2 border-t border-line">
          <div className="grid grid-cols-2 gap-[14px]">
            <div>
              <div className="font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
                Signal Data
              </div>
              <div className="rounded-[4px] border border-line bg-surface px-3 py-2.5 space-y-3">
                {signalHasContent ? (
                  <DetailList data={signal!} />
                ) : (
                  <p className="text-xs text-muted-foreground italic">
                    No signal data — this proposal was created directly by the
                    judge's portfolio review, not by the factor pipeline.
                  </p>
                )}
                {constraintBlocked && (
                  <div className="rounded-[4px] border border-loss/30 bg-loss/10 px-3 py-2">
                    <p className="text-[10.5px] font-mono font-semibold uppercase tracking-wider text-loss mb-1.5">
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
              <div className="font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
                Judge Response
              </div>
              <div className="rounded-[4px] border border-line bg-surface px-3 py-2.5">
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
    <div className="border-b border-line last:border-b-0">
      <div className="flex items-center gap-4 px-6 py-6 bg-bg-2">
        <div className="flex items-center justify-center h-11 w-11 rounded-full bg-warn/15 text-warn shrink-0">
          <ShieldAlert className="h-[22px] w-[22px]" />
        </div>
        <div className="flex-1">
          <div className="text-[13px] font-semibold mb-1">No Trades — Pipeline declared HOLD</div>
          {assessment && (
            <div className="text-[12px] text-muted-foreground leading-[1.5] max-w-2xl">
              {assessment}
            </div>
          )}
        </div>
        <div className="text-right shrink-0">
          {verdict && (
            <Badge variant={verdict === "agree" ? "warn" : "loss"}>
              VERDICT: {verdict === "agree" ? "AGREE" : "DISAGREE"}
            </Badge>
          )}
          {confidence != null && (
            <div className="font-mono text-[11px] text-muted-foreground mt-1">
              Confidence {(confidence * 100).toFixed(0)}%
            </div>
          )}
        </div>
      </div>

      {judge && (
        <div className="px-4 py-2 border-t border-line">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1 font-mono text-[10.5px] text-muted-foreground hover:text-foreground transition-colors uppercase tracking-[0.08em]"
          >
            {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {expanded ? "Hide portfolio review" : "Show portfolio review"}
          </button>
          {expanded && (
            <div className="mt-2 mb-2 rounded-[4px] border border-line bg-surface px-3 py-2.5">
              <DetailList data={judge} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Proposals we don't want cluttering the Trades page. They still live in the
// DB (decision_outcomes uses them to evaluate model signal quality) but we
// don't render their rows by default — only their count in the group header.
const HIDDEN_STATUSES = new Set(["JUDGE_REJECTED", "REJECTED", "BLOCKED"])

/**
 * Tiny hover-tooltip used next to status badges. Pure CSS, no portal —
 * pops out below the icon on hover. Keep ``text`` short (one or two lines).
 *
 * Styled as a small primary-tinted pill so it reads as "click/hover me for
 * info" instead of disappearing into the surrounding chrome.
 */
function HelpHint({ text }: { text: string }) {
  return (
    <span className="relative inline-flex group">
      <span
        className="inline-flex h-[18px] w-[18px] items-center justify-center rounded-[3px] border border-primary/30 bg-primary/10 text-primary cursor-help transition-colors group-hover:border-primary group-hover:bg-primary/20"
        aria-label="More info"
      >
        {/* Geometric "i" glyph matching the TRADE/MARK logo style:
            a small square dot above a straight stem. No curves, no serifs. */}
        <svg width="10" height="12" viewBox="0 0 10 12" fill="none" aria-hidden="true">
          <rect x="4" y="1" width="2" height="2" fill="currentColor" />
          <line x1="5" y1="5" x2="5" y2="11" stroke="currentColor" strokeWidth="2" />
        </svg>
      </span>
      <span
        role="tooltip"
        className="pointer-events-none absolute left-1/2 top-full z-50 mt-1.5 w-[260px] -translate-x-1/2 rounded-[4px] border border-primary/40 bg-surface px-2.5 py-1.5 text-[11px] leading-snug text-foreground shadow-lg shadow-black/40 opacity-0 transition-opacity duration-150 group-hover:opacity-100"
      >
        {text}
      </span>
    </span>
  )
}

interface RunGroup {
  run_id: string
  timestamp: string
  proposals: Proposal[]
  hiddenCount: number  // proposals filtered by HIDDEN_STATUSES, kept for header chip
  hiddenProposals: Proposal[]  // the actual filtered rows so they can be re-expanded on demand
}

function buildRunSummary(proposals: Proposal[], hiddenCount: number = 0): string {
  const trades = proposals.filter((p) => p.action !== "STAY")
  if (trades.length === 0) {
    if (hiddenCount > 0) {
      return `All ${hiddenCount} proposal${hiddenCount === 1 ? "" : "s"} were rejected by the judge — nothing actionable.`
    }
    return "No trades proposed — holding all positions."
  }

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

// Window during which we treat a STAY-only run as "still in progress" rather
// than a finalized HOLD. The pipeline writes the STAY pre-judge and may add
// real trades up to ~60s later; this buffer prevents a HOLD card from
// appearing and then flipping to trades.
const STAY_SETTLE_MS = 120_000

function groupByRun(proposals: Proposal[]): RunGroup[] {
  const groups = new Map<string, Proposal[]>()
  for (const p of proposals) {
    const key = p.run_id || "unknown"
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(p)
  }
  const now = Date.now()

  return Array.from(groups.entries())
    .map(([run_id, all]) => {
      // Filter HIDDEN_STATUSES at the group level (not before grouping) so a
      // run whose only proposals were JUDGE_REJECTED still appears with a
      // "X hidden" header chip — the user wanted those rows hidden, but
      // making the entire run disappear was confusing (it looked like the
      // pipeline never produced anything).
      const hiddenProposals = all.filter((p) => HIDDEN_STATUSES.has(p.status))
      const hiddenCount = hiddenProposals.length
      const surviving = all.filter((p) => !HIDDEN_STATUSES.has(p.status))

      // Once any real trade exists for a run, the early STAY is obsolete.
      const hasTrades = surviving.some((p) => p.action !== "STAY")
      const visible = hasTrades
        ? surviving.filter((p) => p.action !== "STAY")
        : surviving

      const newest = all.reduce((max, p) => {
        const t = p.created_at ? new Date(p.created_at).getTime() : 0
        return t > max ? t : max
      }, 0)
      return {
        run_id,
        timestamp: visible[0]?.created_at || all[0]?.created_at || "",
        proposals: visible,
        hasTrades,
        newest,
        hiddenCount,
        hiddenProposals,
        hasAnyRaw: all.length > 0,
      }
    })
    // STAY-only runs are hidden during the settle window so a placeholder
    // STAY doesn't flash before real trades arrive. After the window passes,
    // they render as a confirmed HOLD.
    // Runs where every proposal was filtered (hiddenCount > 0 but visible=0)
    // still render — we want the user to see the run happened, just without
    // the noisy rejected rows.
    .filter((g) => {
      if (g.hasTrades) return true
      if (g.hiddenCount > 0) return true
      return now - g.newest > STAY_SETTLE_MS
    })
    .map(({ run_id, timestamp, proposals, hiddenCount, hiddenProposals }) => ({
      run_id, timestamp, proposals, hiddenCount, hiddenProposals,
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

  // Tick state forces groupByRun to re-evaluate its time-based settle filter
  // periodically, so a STAY-only run becomes visible once the window passes
  // even if no fresh data has arrived.
  const [, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000)
    return () => clearInterval(id)
  }, [])

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

  // Per-group toggle for "show judge-rejected proposals". Default hidden;
  // user can click the count chip in the header to reveal them inline.
  const [expandedRejectedRuns, setExpandedRejectedRuns] = useState<Set<string>>(new Set())
  const toggleRejected = (runId: string) => {
    setExpandedRejectedRuns((prev) => {
      const next = new Set(prev)
      if (next.has(runId)) next.delete(runId)
      else next.add(runId)
      return next
    })
  }

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
        <PageHeader title="Trades" />
        <div className="space-y-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-24 rounded-md border border-line bg-surface animate-shimmer" />
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

  const totalRuns = groupByRun(all).length
  const description = `${all.length} total proposal${all.length === 1 ? "" : "s"} across ${totalRuns} pipeline run${totalRuns === 1 ? "" : "s"}`

  return (
    <>
      <PageHeader title="Trades" description={description} />

      <div className="grid grid-cols-4 gap-4 mb-[18px]">
        <MetricCard accent label="Pending Review" value={String(pending)} sub="awaiting approval" />
        <MetricCard label="Approved" value={String(approved)} sub="judge-cleared" />
        <MetricCard label="Executed" value={String(executed)} sub="confirmed fills" />
        <MetricCard label="Rejected" value={String(rejected)} sub="declined" />
      </div>

      <div className="flex items-center gap-1.5 mb-[14px]">
        {statuses.map((s) => (
          <Button
            key={s}
            variant={filter === s ? "primary" : "default"}
            size="sm"
            onClick={() => setFilter(s)}
          >
            {s}
          </Button>
        ))}
        <span className="flex-1" />
        <span className="font-mono text-[11px] text-muted-foreground">
          Showing {runGroups.length} run{runGroups.length === 1 ? "" : "s"}
        </span>
      </div>

      {runGroups.length === 0 ? (
        <Card>
          <p className="text-sm text-muted-foreground py-12 text-center">
            No trade proposals. Run the pipeline to generate signals.
          </p>
        </Card>
      ) : (
        <div className="space-y-4">
          {runGroups.map((group) => {
            const isLatestRun = !!(lastCompletedRunId && group.run_id === lastCompletedRunId)
            const tradeCount = group.proposals.filter((p) => p.action !== "STAY").length
            const shortRunId = group.run_id === "unknown" ? "—" : (
              group.run_id.length > 28 ? group.run_id.slice(0, 28) + "…" : group.run_id
            )
            return (
              <Card
                key={group.run_id}
                ref={isLatestRun ? highlightRef : undefined}
                className={cn(isLatestRun && "ring-1 ring-primary/40")}
              >
                {/* Card head */}
                <div className={cn(
                  "flex items-center gap-3 px-4 py-3 border-b border-line",
                  isLatestRun && "bg-primary/[0.06]",
                )}>
                  <span className={cn(
                    "font-mono text-[10.5px] font-semibold uppercase tracking-[0.1em]",
                    isLatestRun ? "text-primary" : "text-muted-foreground",
                  )}>
                    {shortRunId}
                  </span>
                  {isLatestRun && <Badge variant="solid-accent">LATEST</Badge>}
                  <span className="font-mono text-[10.5px] text-muted-2 tracking-[0.04em]">
                    {formatTimestamp(group.timestamp)}
                  </span>
                  {(() => {
                    // Three states with distinct visual weight:
                    //   trades > 0     → muted count badge (the normal case)
                    //   all rejected   → amber "REJECTED BY JUDGE" (judge killed everything; worth attention)
                    //   nothing fired  → blue "HOLD" (calm market, pipeline genuinely had no signals)
                    if (tradeCount > 0) {
                      return (
                        <span className="inline-flex items-center gap-1.5">
                          <Badge variant="muted">
                            {`${tradeCount} TRADE${tradeCount === 1 ? "" : "S"}`}
                          </Badge>
                          <HelpHint text="The pipeline produced trade proposals that survived the LLM judge. Each row below shows a BUY, SELL, or TRIM you can approve or reject." />
                        </span>
                      )
                    }
                    if (group.hiddenCount > 0) {
                      const isExpanded = expandedRejectedRuns.has(group.run_id)
                      return (
                        <span className="inline-flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => toggleRejected(group.run_id)}
                            className="inline-flex items-center gap-1.5 rounded-[3px] border border-warn bg-warn/10 px-[7px] py-[2px] font-mono text-[10px] font-semibold uppercase leading-snug tracking-[0.06em] text-warn whitespace-nowrap cursor-pointer transition-colors hover:bg-warn/20 hover:border-warn"
                            title={isExpanded ? "Hide rejected proposals" : "Click to show the rejected proposals"}
                          >
                            {isExpanded ? (
                              <ChevronDown className="h-3 w-3" strokeWidth={2.4} />
                            ) : (
                              <ChevronRight className="h-3 w-3" strokeWidth={2.4} />
                            )}
                            REJECTED BY JUDGE
                          </button>
                          <HelpHint text="The pipeline produced trade ideas, but the LLM judge rejected all of them after reviewing news, fundamentals, and risk. The signals didn't meet the quality bar. Click the badge to inspect the rejected proposals." />
                        </span>
                      )
                    }
                    return (
                      <span className="inline-flex items-center gap-1.5">
                        <Badge variant="info">HOLD</Badge>
                        <HelpHint text="No actionable signals fired this run. The model didn't see enough conviction in any ticker to recommend a trade — staying put is the right call." />
                      </span>
                    )
                  })()}
                  {group.hiddenCount > 0 && tradeCount > 0 && (
                    <button
                      type="button"
                      onClick={() => toggleRejected(group.run_id)}
                      className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground hover:text-warn transition-colors cursor-pointer"
                      title="Click to show / hide the proposals the judge rejected."
                    >
                      {expandedRejectedRuns.has(group.run_id) ? (
                        <ChevronDown className="h-3 w-3" strokeWidth={2.4} />
                      ) : (
                        <ChevronRight className="h-3 w-3" strokeWidth={2.4} />
                      )}
                      {group.hiddenCount} judge-rejected
                    </button>
                  )}
                  <span className="flex-1" />
                  {isLatestRun && (
                    <button
                      onClick={clearLastCompletedRunId}
                      className="flex items-center justify-center h-[24px] w-[24px] rounded-[4px] text-muted-foreground hover:bg-surface-2 hover:text-foreground transition-colors"
                      title="Dismiss highlight"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                  {group.run_id !== "unknown" && (
                    <div className="relative" ref={menuOpenRunId === group.run_id ? menuRef : undefined}>
                      <button
                        onClick={() => setMenuOpenRunId(menuOpenRunId === group.run_id ? null : group.run_id)}
                        className="flex items-center justify-center h-[24px] w-[24px] rounded-[4px] text-muted-foreground hover:bg-loss/10 hover:text-loss transition-colors"
                        title="Delete this pipeline run"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                      {menuOpenRunId === group.run_id && (
                        <div className="absolute right-0 top-full mt-1 z-50 w-40 rounded-[4px] border border-line bg-surface shadow-xl shadow-black/40 py-1">
                          <button
                            onClick={() => deleteRunMut.mutate(group.run_id)}
                            disabled={deleteRunMut.isPending}
                            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-loss hover:bg-loss/10 transition-colors disabled:opacity-50"
                          >
                            <Trash2 className="h-3 w-3" />
                            {deleteRunMut.isPending ? "Deleting..." : "Delete run"}
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Summary row */}
                <div className="px-4 py-2.5 text-[12px] text-fg-dim border-b border-line">
                  {buildRunSummary(group.proposals, group.hiddenCount)}
                </div>

                {/* Proposals */}
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

                {/* Judge-rejected proposals — collapsed by default, expanded
                    on demand via the header button. Rendered dimmed to make
                    it visually obvious these aren't actionable. */}
                {expandedRejectedRuns.has(group.run_id) && group.hiddenProposals.length > 0 && (
                  <div className="border-t border-line bg-bg-2/40">
                    <div className="px-4 py-2 flex items-center gap-2">
                      <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.1em] text-warn">
                        Rejected by judge · {group.hiddenProposals.length}
                      </span>
                      <span className="font-mono text-[10px] text-muted-2">
                        — shown for audit, not actionable
                      </span>
                    </div>
                    <div className="opacity-60">
                      {group.hiddenProposals.map((p) => (
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
                  </div>
                )}
              </Card>
            )
          })}
        </div>
      )}
    </>
  )
}
