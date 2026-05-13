import { useState } from "react"
import type { PipelineEvent } from "@/contexts/pipeline-context"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { DataTable, type Column } from "@/components/ui/data-table"
import { cn, formatPercent } from "@/lib/utils"
import {
  Hand, Play, XCircle, Trash2, ChevronDown, ChevronUp,
  MessageSquarePlus, Check, Shield,
} from "lucide-react"

interface GateReviewPanelProps {
  gate: PipelineEvent
  onContinue: (overrides?: Record<string, unknown>) => void
  onAbort: () => void
}

// ─── Gate container ───
export function GateReviewPanel({ gate, onContinue, onAbort }: GateReviewPanelProps) {
  const data = gate.gate_data ?? {}
  const name = gate.gate_name ?? ""

  return (
    <Card className="border-2 border-amber-500/40 bg-amber-500/[0.02]">
      <CardTitle>
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center h-8 w-8 rounded-lg bg-amber-500/15">
            <Hand className="h-4 w-4 text-amber-500" />
          </div>
          <div className="flex-1">
            <span className="text-amber-400">Review Required</span>
            <span className="text-muted-foreground text-xs ml-2">{gate.message}</span>
          </div>
          <Badge variant="default" className="bg-amber-500/20 text-amber-400 border-amber-500/30 text-[10px]">
            WAITING
          </Badge>
        </div>
      </CardTitle>
      <CardContent>
        <GateContent name={name} data={data} onContinue={onContinue} onAbort={onAbort} />
      </CardContent>
    </Card>
  )
}

function GateContent({ name, data, onContinue, onAbort }: {
  name: string
  data: Record<string, unknown>
  onContinue: (overrides?: Record<string, unknown>) => void
  onAbort: () => void
}) {
  switch (name) {
    case "scoring_review":
      return <ScoringReview data={data} onContinue={onContinue} onAbort={onAbort} />
    case "signals_review":
      return <SignalsReview data={data} onContinue={onContinue} onAbort={onAbort} />
    case "proposals_review":
      return <ProposalsReview data={data} onContinue={onContinue} onAbort={onAbort} />
    case "research_review":
      return <ResearchReview data={data} onContinue={onContinue} onAbort={onAbort} />
    case "judge_review":
      return <JudgeReview data={data} onContinue={onContinue} onAbort={onAbort} />
    case "execution_review":
      return <ExecutionReview data={data} onContinue={onContinue} onAbort={onAbort} />
    default:
      return <GenericReview data={data} onContinue={onContinue} onAbort={onAbort} />
  }
}

function GateActions({ onContinue, onAbort, continueLabel = "Continue", disabled = false }: {
  onContinue: () => void
  onAbort: () => void
  continueLabel?: string
  disabled?: boolean
}) {
  return (
    <div className="flex items-center justify-end gap-3 mt-4 pt-4 border-t border-border/40">
      <Button variant="outline" size="sm" onClick={onAbort} className="border-loss/30 text-loss hover:bg-loss/10">
        <XCircle className="h-3.5 w-3.5 mr-1.5" />
        Abort Pipeline
      </Button>
      <Button size="sm" onClick={onContinue} disabled={disabled} className="bg-primary hover:bg-primary/90 text-background border-primary">
        <Play className="h-3.5 w-3.5 mr-1.5" />
        {continueLabel}
      </Button>
    </div>
  )
}

// ─── Scoring Review ───
interface ScoreRow {
  ticker: string
  composite_score: number
  score_decile: number
  momentum_12m1m: number | null
  eps_growth_yoy: number | null
  revenue_growth_yoy: number | null
  gross_margin_trend: number | null
  relative_valuation: number | null
  is_good_stock?: boolean
  quality_score?: number
}

function ScoringReview({ data, onContinue, onAbort }: { data: Record<string, unknown>; onContinue: (o?: Record<string, unknown>) => void; onAbort: () => void }) {
  const scores = (data.scores ?? []) as ScoreRow[]
  const [excluded, setExcluded] = useState<Set<string>>(new Set())

  const toggleExclude = (ticker: string) => {
    setExcluded((prev) => {
      const next = new Set(prev)
      if (next.has(ticker)) next.delete(ticker)
      else next.add(ticker)
      return next
    })
  }

  const columns: Column<ScoreRow>[] = [
    {
      key: "exclude",
      header: "",
      render: (r) => (
        <button onClick={() => toggleExclude(r.ticker)} className="p-1 hover:bg-muted/60 rounded">
          {excluded.has(r.ticker) ? <Trash2 className="h-3.5 w-3.5 text-loss" /> : <Check className="h-3.5 w-3.5 text-muted-foreground/40" />}
        </button>
      ),
    },
    { key: "ticker", header: "Ticker", render: (r) => <span className={cn("font-medium", excluded.has(r.ticker) && "line-through text-muted-foreground")}>{r.ticker}</span> },
    { key: "composite_score", header: "Score", align: "right", render: (r) => <span>{r.composite_score?.toFixed(2)}</span> },
    { key: "score_decile", header: "Decile", align: "right", render: (r) => <span>{r.score_decile}</span> },
    { key: "momentum_12m1m", header: "Mom 12-1", align: "right", render: (r) => <span className={cn(r.momentum_12m1m != null && r.momentum_12m1m > 0 ? "text-profit" : "text-loss")}>{r.momentum_12m1m != null ? formatPercent(r.momentum_12m1m) : "-"}</span> },
    { key: "eps_growth_yoy", header: "EPS YoY", align: "right", render: (r) => <span className={cn(r.eps_growth_yoy != null && r.eps_growth_yoy > 0 ? "text-profit" : "text-loss")}>{r.eps_growth_yoy != null ? formatPercent(r.eps_growth_yoy) : "-"}</span> },
    { key: "quality_score", header: "Quality", align: "right", render: (r) => r.quality_score != null ? <span>{(r.quality_score * 100).toFixed(0)}</span> : <span className="text-muted-foreground">-</span> },
    { key: "is_good_stock", header: "Good?", render: (r) => r.is_good_stock != null ? <Badge variant={r.is_good_stock ? "profit" : "muted"}>{r.is_good_stock ? "Yes" : "No"}</Badge> : null },
  ]

  return (
    <div>
      <p className="text-xs text-muted-foreground mb-3">
        Top 30 of {data.total_count as number} scored tickers (as of {data.as_of_date as string}).
        Click the check icon to exclude tickers from this run.
      </p>
      <div className="max-h-[24rem] overflow-y-auto">
        <DataTable columns={columns} data={scores} rowKey={(r) => r.ticker} compact />
      </div>
      {excluded.size > 0 && (
        <p className="text-xs text-amber-400 mt-2">{excluded.size} ticker(s) will be excluded</p>
      )}
      <GateActions
        onContinue={() => onContinue(excluded.size > 0 ? { exclude_tickers: Array.from(excluded) } : undefined)}
        onAbort={onAbort}
      />
    </div>
  )
}

// ─── Signals Review ───
interface SignalRow {
  ticker: string
  action: string
  target_weight: number
  current_weight: number
  reason: string
  signal_data?: Record<string, unknown>
}

function SignalsReview({ data, onContinue, onAbort }: { data: Record<string, unknown>; onContinue: (o?: Record<string, unknown>) => void; onAbort: () => void }) {
  const signals = (data.actionable_signals ?? []) as SignalRow[]
  const [removed, setRemoved] = useState<Set<string>>(new Set())

  const columns: Column<SignalRow>[] = [
    {
      key: "remove",
      header: "",
      render: (r) => (
        <button onClick={() => setRemoved((prev) => { const n = new Set(prev); n.has(r.ticker) ? n.delete(r.ticker) : n.add(r.ticker); return n })} className="p-1 hover:bg-muted/60 rounded">
          {removed.has(r.ticker) ? <Trash2 className="h-3.5 w-3.5 text-loss" /> : <Check className="h-3.5 w-3.5 text-muted-foreground/40" />}
        </button>
      ),
    },
    { key: "ticker", header: "Ticker", render: (r) => <span className={cn("font-medium", removed.has(r.ticker) && "line-through text-muted-foreground")}>{r.ticker}</span> },
    { key: "action", header: "Action", render: (r) => <Badge variant={r.action === "BUY" ? "default" : r.action === "SELL" ? "loss" : "muted"}>{r.action}</Badge> },
    { key: "current_weight", header: "Current", align: "right", render: (r) => <span>{formatPercent(r.current_weight)}</span> },
    { key: "target_weight", header: "Target", align: "right", render: (r) => <span className="font-medium">{formatPercent(r.target_weight)}</span> },
    { key: "reason", header: "Reason", render: (r) => <span className="text-xs text-muted-foreground max-w-[16rem] truncate block">{r.reason}</span> },
  ]

  return (
    <div>
      <p className="text-xs text-muted-foreground mb-3">
        {signals.length} actionable signals out of {data.total_signals as number} total.
        Remove signals you don't want the pipeline to act on.
      </p>
      <div className="max-h-[20rem] overflow-y-auto">
        <DataTable columns={columns} data={signals} rowKey={(r) => r.ticker} compact />
      </div>
      {removed.size > 0 && (
        <p className="text-xs text-amber-400 mt-2">{removed.size} signal(s) will be removed</p>
      )}
      <GateActions
        onContinue={() => onContinue(removed.size > 0 ? { remove_tickers: Array.from(removed) } : undefined)}
        onAbort={onAbort}
      />
    </div>
  )
}

// ─── Proposals Review ───
interface ProposalRow {
  proposal_id: string
  ticker: string
  action: string
  shares: number
  estimated_value?: number
  current_weight?: number
  target_weight?: number
  constraint_check: { passed: boolean; violations?: string[] }
  reason?: string
}

function ProposalsReview({ data, onContinue, onAbort }: { data: Record<string, unknown>; onContinue: (o?: Record<string, unknown>) => void; onAbort: () => void }) {
  const proposals = (data.proposals ?? []) as ProposalRow[]
  const [removedIds, setRemovedIds] = useState<Set<string>>(new Set())
  const [forcedIds, setForcedIds] = useState<Set<string>>(new Set())

  const toggleRemove = (id: string) => setRemovedIds((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  const toggleForce = (id: string) => setForcedIds((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })

  const columns: Column<ProposalRow>[] = [
    {
      key: "remove",
      header: "",
      render: (r) => (
        <button onClick={() => toggleRemove(r.proposal_id)} className="p-1 hover:bg-muted/60 rounded">
          {removedIds.has(r.proposal_id) ? <Trash2 className="h-3.5 w-3.5 text-loss" /> : <Check className="h-3.5 w-3.5 text-muted-foreground/40" />}
        </button>
      ),
    },
    { key: "ticker", header: "Ticker", render: (r) => <span className={cn("font-medium", removedIds.has(r.proposal_id) && "line-through text-muted-foreground")}>{r.ticker}</span> },
    { key: "action", header: "Action", render: (r) => <Badge variant={r.action === "BUY" ? "default" : r.action === "SELL" ? "loss" : "muted"}>{r.action}</Badge> },
    { key: "shares", header: "Shares", align: "right", render: (r) => <span>{r.shares}</span> },
    { key: "estimated_value", header: "Value", align: "right", render: (r) => <span>${(r.estimated_value ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span> },
    { key: "target_weight", header: "Target Wt", align: "right", render: (r) => <span>{r.target_weight != null ? formatPercent(r.target_weight) : "-"}</span> },
    {
      key: "constraint",
      header: "Constraint",
      render: (r) => {
        const passed = r.constraint_check?.passed ?? true
        const forced = forcedIds.has(r.proposal_id)
        if (passed || forced) return <Badge variant="profit">{forced ? "FORCED" : "PASS"}</Badge>
        return (
          <div className="flex items-center gap-1">
            <Badge variant="loss">BLOCKED</Badge>
            <button onClick={() => toggleForce(r.proposal_id)} className="text-[10px] text-amber-400 hover:underline ml-1">Force</button>
          </div>
        )
      },
    },
    { key: "reason", header: "Reason", render: (r) => <span className="text-xs text-muted-foreground max-w-[14rem] truncate block">{r.reason}</span> },
  ]

  return (
    <div>
      <p className="text-xs text-muted-foreground mb-3">
        {data.passed_count as number} passed constraints, {data.blocked_count as number} blocked.
        Remove proposals or force through blocked ones.
      </p>
      <div className="max-h-[20rem] overflow-y-auto">
        <DataTable columns={columns} data={proposals} rowKey={(r) => r.proposal_id} compact />
      </div>
      <GateActions
        onContinue={() => {
          const overrides: Record<string, unknown> = {}
          if (removedIds.size > 0) overrides.remove_proposal_ids = Array.from(removedIds)
          if (forcedIds.size > 0) overrides.force_through_ids = Array.from(forcedIds)
          onContinue(Object.keys(overrides).length > 0 ? overrides : undefined)
        }}
        onAbort={onAbort}
      />
    </div>
  )
}

// ─── Research Review ───
interface ResearchRow {
  ticker: string
  headlines: string[]
  ai_summary: string
  sentiment: string
  confidence: number
  risk_factors: string[]
  opportunities: string[]
  binary_events: Array<{ event_type?: string; description?: string }>
  data_sources: string[]
}

function ResearchReview({ data, onContinue, onAbort }: { data: Record<string, unknown>; onContinue: (o?: Record<string, unknown>) => void; onAbort: () => void }) {
  const research = (data.research ?? []) as ResearchRow[]
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [userContext, setUserContext] = useState<Record<string, string>>({})

  const toggle = (ticker: string) => setExpanded((prev) => { const n = new Set(prev); n.has(ticker) ? n.delete(ticker) : n.add(ticker); return n })

  return (
    <div>
      <p className="text-xs text-muted-foreground mb-3">
        News research for {data.total_tickers as number} tickers. Expand to view details and add your own context.
      </p>
      <div className="max-h-[28rem] overflow-y-auto space-y-2">
        {research.map((r) => {
          const isOpen = expanded.has(r.ticker)
          const sentimentColor = r.sentiment === "bullish" ? "text-profit" : r.sentiment === "bearish" ? "text-loss" : "text-muted-foreground"
          return (
            <div key={r.ticker} className="rounded-lg border border-border/40 bg-card/50">
              <button onClick={() => toggle(r.ticker)} className="w-full flex items-center gap-3 px-3 py-2.5 text-left">
                <span className="font-medium text-sm">{r.ticker}</span>
                <Badge variant={r.sentiment === "bullish" ? "profit" : r.sentiment === "bearish" ? "loss" : "muted"} className="text-[10px]">
                  {r.sentiment || "neutral"}
                </Badge>
                <span className="text-xs text-muted-foreground flex-1 truncate">{r.headlines?.[0] ?? "No headlines"}</span>
                <span className="text-xs text-muted-foreground/60">{r.confidence > 0 ? `${(r.confidence * 100).toFixed(0)}%` : "—"}</span>
                {isOpen ? <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />}
              </button>
              {isOpen && (
                <div className="px-3 pb-3 space-y-2">
                  {r.ai_summary && (
                    <p className="text-xs text-foreground/80 leading-relaxed">{r.ai_summary}</p>
                  )}
                  {r.headlines?.length > 0 && (
                    <div>
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Headlines</p>
                      <ul className="text-xs text-muted-foreground space-y-0.5 list-disc list-inside">
                        {r.headlines.slice(0, 5).map((h, i) => <li key={i}>{h}</li>)}
                      </ul>
                    </div>
                  )}
                  {r.risk_factors?.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {r.risk_factors.map((f, i) => <Badge key={i} variant="loss" className="text-[10px]">{f}</Badge>)}
                    </div>
                  )}
                  {r.opportunities?.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {r.opportunities.map((o, i) => <Badge key={i} variant="profit" className="text-[10px]">{o}</Badge>)}
                    </div>
                  )}
                  {r.binary_events?.length > 0 && (
                    <div>
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Binary Events</p>
                      <ul className="text-xs text-amber-400/80 space-y-0.5">
                        {r.binary_events.map((e, i) => <li key={i}>{e.description || e.event_type || "Event"}</li>)}
                      </ul>
                    </div>
                  )}
                  <div>
                    <div className="flex items-center gap-1 mb-1">
                      <MessageSquarePlus className="h-3 w-3 text-info" />
                      <p className="text-[10px] font-semibold text-info uppercase tracking-wider">Add Your Context</p>
                    </div>
                    <textarea
                      value={userContext[r.ticker] ?? ""}
                      onChange={(e) => setUserContext((prev) => ({ ...prev, [r.ticker]: e.target.value }))}
                      placeholder="Add notes, links, or observations for the judge..."
                      className="w-full h-16 rounded-md bg-[#050706] border border-border/60 px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground/40 resize-none focus:outline-none focus:border-info/50"
                    />
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
      <GateActions
        onContinue={() => {
          const filteredContext = Object.fromEntries(Object.entries(userContext).filter(([, v]) => v.trim()))
          onContinue(Object.keys(filteredContext).length > 0 ? { user_context: filteredContext } : undefined)
        }}
        onAbort={onAbort}
        continueLabel="Continue to Judge"
      />
    </div>
  )
}

// ─── Judge Review ───
interface JudgeRow {
  proposal_id: string
  ticker: string
  action: string
  shares: number
  verdict: string
  confidence: number
  reasons: string[]
  risk_flags: string[]
  violated_rules?: string[]
  binary_event_warning?: string | null
  follow_up_checks?: string[]
  status: string
}

function JudgeReview({ data, onContinue, onAbort }: { data: Record<string, unknown>; onContinue: (o?: Record<string, unknown>) => void; onAbort: () => void }) {
  const results = (data.judge_results ?? []) as JudgeRow[]
  const [overrides, setOverrides] = useState<Record<string, { verdict: string; notes: string }>>({})
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggle = (id: string) => setExpanded((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })

  const setOverride = (id: string, verdict: string) => {
    setOverrides((prev) => ({ ...prev, [id]: { verdict, notes: prev[id]?.notes ?? "" } }))
  }

  return (
    <div>
      <p className="text-xs text-muted-foreground mb-3">
        Review judge verdicts. Override any decision before execution proceeds.
      </p>
      <div className="max-h-[28rem] overflow-y-auto space-y-2">
        {results.map((r) => {
          const isOpen = expanded.has(r.proposal_id)
          const override = overrides[r.proposal_id]
          const effectiveVerdict = override?.verdict ?? r.verdict
          const isApproved = effectiveVerdict === "approve"
          const isRejected = effectiveVerdict === "reject"

          return (
            <div key={r.proposal_id} className={cn(
              "rounded-lg border bg-card/50",
              isApproved ? "border-profit/30" : isRejected ? "border-loss/30" : "border-amber-500/30",
            )}>
              <div className="flex items-center gap-3 px-3 py-2.5">
                <span className="font-medium text-sm w-14">{r.ticker}</span>
                <Badge variant={r.action === "BUY" ? "default" : r.action === "SELL" ? "loss" : "muted"} className="text-[10px]">{r.action}</Badge>
                <span className="text-xs text-muted-foreground">{r.shares} shares</span>

                <div className="flex-1" />

                <span className="text-xs text-muted-foreground">{(r.confidence * 100).toFixed(0)}%</span>

                {/* Verdict override buttons */}
                <div className="flex gap-1">
                  <button
                    onClick={() => setOverride(r.proposal_id, "approve")}
                    className={cn(
                      "px-2 py-1 rounded text-[10px] font-medium border transition-colors",
                      effectiveVerdict === "approve"
                        ? "bg-profit/20 border-profit/40 text-profit"
                        : "border-border/40 text-muted-foreground hover:border-profit/30 hover:text-profit",
                    )}
                  >
                    APPROVE
                  </button>
                  <button
                    onClick={() => setOverride(r.proposal_id, "reject")}
                    className={cn(
                      "px-2 py-1 rounded text-[10px] font-medium border transition-colors",
                      effectiveVerdict === "reject"
                        ? "bg-loss/20 border-loss/40 text-loss"
                        : "border-border/40 text-muted-foreground hover:border-loss/30 hover:text-loss",
                    )}
                  >
                    REJECT
                  </button>
                </div>

                <button onClick={() => toggle(r.proposal_id)} className="p-1">
                  {isOpen ? <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />}
                </button>
              </div>

              {isOpen && (
                <div className="px-3 pb-3 space-y-2 border-t border-border/20 pt-2">
                  {r.reasons?.length > 0 && (
                    <div>
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Reasons</p>
                      <ul className="text-xs text-foreground/80 space-y-0.5 list-disc list-inside">
                        {r.reasons.map((reason, i) => <li key={i}>{reason}</li>)}
                      </ul>
                    </div>
                  )}
                  {r.risk_flags?.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      <Shield className="h-3 w-3 text-amber-400 mt-0.5" />
                      {r.risk_flags.map((f, i) => <Badge key={i} variant="loss" className="text-[10px]">{f}</Badge>)}
                    </div>
                  )}
                  {r.binary_event_warning && (
                    <p className="text-xs text-amber-400">{r.binary_event_warning}</p>
                  )}
                  {override && (
                    <textarea
                      value={override.notes}
                      onChange={(e) => setOverrides((prev) => ({
                        ...prev,
                        [r.proposal_id]: { ...prev[r.proposal_id], notes: e.target.value },
                      }))}
                      placeholder="Add notes for this override..."
                      className="w-full h-12 rounded-md bg-[#050706] border border-border/60 px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground/40 resize-none focus:outline-none focus:border-info/50"
                    />
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
      <GateActions
        onContinue={() => {
          const verdictOverrides = Object.entries(overrides).map(([id, o]) => ({
            proposal_id: id,
            new_verdict: o.verdict,
            notes: o.notes,
          }))
          onContinue(verdictOverrides.length > 0 ? { verdict_overrides: verdictOverrides } : undefined)
        }}
        onAbort={onAbort}
        continueLabel="Proceed to Execution"
      />
    </div>
  )
}

// ─── Execution Review ───
interface ExecRow {
  proposal_id: string
  ticker: string
  action: string
  shares: number
  estimated_value: number
  price: number
}

function ExecutionReview({ data, onContinue, onAbort }: { data: Record<string, unknown>; onContinue: (o?: Record<string, unknown>) => void; onAbort: () => void }) {
  const trades = (data.trades ?? []) as ExecRow[]
  const [removedIds, setRemovedIds] = useState<Set<string>>(new Set())

  const columns: Column<ExecRow>[] = [
    {
      key: "remove",
      header: "",
      render: (r) => (
        <button onClick={() => setRemovedIds((prev) => { const n = new Set(prev); n.has(r.proposal_id) ? n.delete(r.proposal_id) : n.add(r.proposal_id); return n })} className="p-1 hover:bg-muted/60 rounded">
          {removedIds.has(r.proposal_id) ? <Trash2 className="h-3.5 w-3.5 text-loss" /> : <Check className="h-3.5 w-3.5 text-muted-foreground/40" />}
        </button>
      ),
    },
    { key: "ticker", header: "Ticker", render: (r) => <span className={cn("font-medium", removedIds.has(r.proposal_id) && "line-through text-muted-foreground")}>{r.ticker}</span> },
    { key: "action", header: "Action", render: (r) => <Badge variant={r.action === "BUY" ? "default" : r.action === "SELL" ? "loss" : "muted"}>{r.action}</Badge> },
    { key: "shares", header: "Shares", align: "right", render: (r) => <span>{r.shares}</span> },
    { key: "price", header: "Price", align: "right", render: (r) => <span>${r.price?.toFixed(2)}</span> },
    { key: "estimated_value", header: "Value", align: "right", render: (r) => <span>${r.estimated_value?.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span> },
  ]

  return (
    <div>
      <p className="text-xs text-amber-400 mb-3">
        These trades will be executed immediately. Remove any you want to skip.
      </p>
      <DataTable columns={columns} data={trades} rowKey={(r) => r.proposal_id} compact />
      <GateActions
        onContinue={() => onContinue(removedIds.size > 0 ? { remove_proposal_ids: Array.from(removedIds) } : undefined)}
        onAbort={onAbort}
        continueLabel="Execute Trades"
      />
    </div>
  )
}

// ─── Generic fallback ───
function GenericReview({ data, onContinue, onAbort }: { data: Record<string, unknown>; onContinue: (o?: Record<string, unknown>) => void; onAbort: () => void }) {
  return (
    <div>
      <pre className="text-xs text-muted-foreground max-h-[16rem] overflow-y-auto rounded-lg bg-[#050706] border border-border/40 p-3">
        {JSON.stringify(data, null, 2)}
      </pre>
      <GateActions onContinue={() => onContinue()} onAbort={onAbort} />
    </div>
  )
}
