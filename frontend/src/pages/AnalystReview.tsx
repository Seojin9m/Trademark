import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useState, useEffect, useRef } from "react"
import { api } from "@/lib/api"
import type { AnalystReview as AnalystReviewType } from "@/lib/api"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useToast } from "@/contexts/toast-context"
import { cn } from "@/lib/utils"
import {
  Loader2, BrainCircuit, TrendingUp, TrendingDown, Minus,
  ShieldAlert, Lightbulb, AlertTriangle, CheckCircle, RefreshCw,
  FlaskConical, ChevronRight,
} from "lucide-react"

const STANCE_CONFIG = {
  bullish: { label: "BULLISH", color: "text-profit", border: "border-emerald-500/30 bg-emerald-500/5", icon: TrendingUp },
  neutral: { label: "NEUTRAL", color: "text-muted-foreground", border: "border-border/60 bg-card", icon: Minus },
  bearish: { label: "BEARISH", color: "text-loss", border: "border-red-500/30 bg-red-500/5", icon: TrendingDown },
}

const POSITION_STANCE = {
  add:  { color: "text-profit",          bg: "bg-emerald-500/10 border-emerald-500/30" },
  hold: { color: "text-muted-foreground", bg: "bg-muted/30 border-border/40" },
  trim: { color: "text-amber-400",        bg: "bg-amber-500/10 border-amber-500/30" },
  exit: { color: "text-loss",            bg: "bg-red-500/10 border-red-500/30" },
}

function HealthGauge({ score }: { score: number }) {
  const color = score >= 70 ? "#22c55e" : score >= 45 ? "#f59e0b" : "#ef4444"
  const pct = Math.min(100, Math.max(0, score))
  return (
    <div className="flex items-center gap-3">
      <div className="relative h-3 flex-1 rounded-full bg-muted overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 rounded-full transition-all duration-700"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-lg font-semibold tabular-nums" style={{ color }}>
        {score}
        <span className="text-xs text-muted-foreground font-normal">/100</span>
      </span>
    </div>
  )
}

function Section({ icon: Icon, title, items, color }: {
  icon: React.ElementType
  title: string
  items: string[]
  color: string
}) {
  if (!items?.length) return null
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <Icon className={cn("h-4 w-4", color)} />
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
      </div>
      <ul className="space-y-1.5">
        {items.map((item, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-foreground/80">
            <ChevronRight className={cn("h-3.5 w-3.5 mt-0.5 shrink-0", color)} />
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}

function ReviewDisplay({ review, onApplyToggle, applyPending }: {
  review: AnalystReviewType
  onApplyToggle: () => void
  applyPending: boolean
}) {
  const cfg = STANCE_CONFIG[review.overall_stance] ?? STANCE_CONFIG.neutral
  const StanceIcon = cfg.icon
  const age = Math.round((Date.now() - new Date(review.created_at).getTime()) / 60000)
  const ageLabel = age < 60 ? `${age}m ago` : `${Math.round(age / 60)}h ago`

  return (
    <div className="space-y-4">
      {/* Header card */}
      <div className={cn("rounded-xl border-2 p-5", cfg.border)}>
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className={cn("flex items-center justify-center h-10 w-10 rounded-lg mt-0.5",
              review.overall_stance === "bullish" ? "bg-emerald-500/15"
              : review.overall_stance === "bearish" ? "bg-red-500/15" : "bg-muted/60")}>
              <StanceIcon className={cn("h-5 w-5", cfg.color)} />
            </div>
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className={cn("text-sm font-bold tracking-wide", cfg.color)}>{cfg.label}</span>
                <span className="text-xs text-muted-foreground">· {ageLabel}</span>
              </div>
              <p className="text-sm text-foreground/80 leading-relaxed max-w-2xl">{review.summary}</p>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={onApplyToggle}
              disabled={applyPending}
              className={cn(
                "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold transition-all",
                review.apply_to_pipeline
                  ? "border-emerald-500/60 bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30"
                  : "border-amber-500/50 bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 hover:border-amber-500/70",
              )}
            >
              {applyPending
                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                : <FlaskConical className="h-3.5 w-3.5" />}
              {review.apply_to_pipeline ? "Applied to pipeline" : "Apply to pipeline"}
            </button>
          </div>
        </div>

        <div className="mt-4 pt-4 border-t border-border/30">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1.5">Portfolio Health</p>
          <HealthGauge score={review.portfolio_health_score} />
        </div>
      </div>

      {/* Market context */}
      {review.market_context && (
        <Card>
          <CardTitle>Market Context</CardTitle>
          <CardContent>
            <p className="text-sm text-foreground/80 leading-relaxed">{review.market_context}</p>
          </CardContent>
        </Card>
      )}

      {/* Position reviews */}
      {review.position_reviews?.length > 0 && (
        <Card>
          <CardTitle>Position-by-Position Assessment</CardTitle>
          <CardContent>
            <div className="space-y-2">
              {review.position_reviews.map((pr) => {
                const s = POSITION_STANCE[pr.stance] ?? POSITION_STANCE.hold
                return (
                  <div key={pr.ticker} className={cn("flex items-start gap-3 rounded-lg border px-3 py-2.5", s.bg)}>
                    <span className="font-bold text-sm w-14 shrink-0">{pr.ticker}</span>
                    <span className={cn("text-xs font-bold uppercase tracking-wide w-8 shrink-0 mt-0.5", s.color)}>
                      {pr.stance}
                    </span>
                    <span className="text-sm text-foreground/80 flex-1">{pr.reasoning}</span>
                    <span className="text-xs text-muted-foreground shrink-0 mt-0.5">
                      {Math.round(pr.conviction * 100)}%
                    </span>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Analysis grid */}
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardContent>
            <div className="space-y-4">
              <Section icon={CheckCircle} title="Strengths" items={review.strengths} color="text-profit" />
              <Section icon={Lightbulb} title="Opportunities" items={review.opportunities} color="text-primary" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent>
            <div className="space-y-4">
              <Section icon={AlertTriangle} title="Concerns" items={review.concerns} color="text-amber-400" />
              <Section icon={ShieldAlert} title="Risk Factors" items={review.risk_factors} color="text-loss" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Pipeline guidance */}
      {review.pipeline_guidance?.length > 0 && (
        <Card className={cn("border-2", review.apply_to_pipeline ? "border-primary/30 bg-primary/5" : "border-border/60")}>
          <CardTitle>
            <div className="flex items-center gap-2">
              <FlaskConical className={cn("h-4 w-4", review.apply_to_pipeline ? "text-primary" : "text-muted-foreground")} />
              Pipeline Guidance
              {review.apply_to_pipeline && (
                <Badge variant="muted" className="text-[10px] bg-primary/15 text-primary border-primary/30">ACTIVE</Badge>
              )}
            </div>
          </CardTitle>
          <CardContent>
            <p className="text-xs text-muted-foreground mb-3">
              {review.apply_to_pipeline
                ? "These instructions will be injected into the LLM judge on the next pipeline run."
                : "Toggle \"Apply to pipeline\" above to inject these into the next pipeline run's judge."}
            </p>
            <ul className="space-y-1.5">
              {review.pipeline_guidance.map((g, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <ChevronRight className={cn("h-3.5 w-3.5 mt-0.5 shrink-0", review.apply_to_pipeline ? "text-primary" : "text-muted-foreground")} />
                  {g}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

const THINKING_STEPS = [
  "Loading portfolio positions and live prices...",
  "Computing factor scores across universe tickers...",
  "Evaluating momentum, valuation, and earnings quality...",
  "Assessing current market regime and volatility...",
  "Reviewing sector concentration and risk exposure...",
  "Generating position-by-position conviction scores...",
  "Cross-referencing historical pattern performance...",
  "Formulating pipeline guidance recommendations...",
  "Drafting portfolio health assessment...",
  "Finalising quantitative review — almost there...",
]

function AnalysisLoadingState() {
  const [visibleCount, setVisibleCount] = useState(1)
  const [cursorVisible, setCursorVisible] = useState(true)
  const logRef = useRef<HTMLDivElement>(null)

  // Advance one step every ~1.8 s, then hold on the last one
  useEffect(() => {
    const id = setInterval(() => {
      setVisibleCount((n) => (n < THINKING_STEPS.length ? n + 1 : n))
    }, 1800)
    return () => clearInterval(id)
  }, [])

  // Blink the cursor
  useEffect(() => {
    const id = setInterval(() => setCursorVisible((v) => !v), 530)
    return () => clearInterval(id)
  }, [])

  // Auto-scroll the log as new lines appear
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [visibleCount])

  return (
    <div className="space-y-4">
      {/* Thinking terminal */}
      <div className="rounded-xl border border-primary/20 bg-[#0a0a10] overflow-hidden">
        {/* Terminal titlebar */}
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-primary/10 bg-primary/5">
          <div className="flex gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-red-500/60" />
            <span className="h-2.5 w-2.5 rounded-full bg-amber-500/60" />
            <span className="h-2.5 w-2.5 rounded-full bg-green-500/60" />
          </div>
          <div className="flex items-center gap-2 ml-2">
            <BrainCircuit className="h-3.5 w-3.5 text-primary animate-pulse" />
            <span className="text-xs font-mono text-primary/70">quant-analyst — analysing portfolio</span>
          </div>
        </div>

        {/* Log lines */}
        <div
          ref={logRef}
          className="px-4 py-3 space-y-1.5 font-mono text-xs overflow-y-auto"
          style={{ minHeight: 180, maxHeight: 260 }}
        >
          {THINKING_STEPS.slice(0, visibleCount).map((step, i) => {
            const isLast = i === visibleCount - 1
            const isDone = i < visibleCount - 1
            return (
              <div
                key={i}
                className="flex items-start gap-2"
                style={{
                  animation: "analyst-step-in 0.25s ease-out both",
                }}
              >
                <span className={cn("shrink-0 mt-px", isDone ? "text-emerald-500" : "text-primary")}>
                  {isDone ? "✓" : "›"}
                </span>
                <span className={cn(isDone ? "text-muted-foreground" : "text-foreground/90")}>
                  {step}
                  {isLast && (
                    <span
                      className="inline-block w-1.5 h-3 ml-0.5 align-middle bg-primary rounded-sm"
                      style={{ opacity: cursorVisible ? 1 : 0, transition: "opacity 0.1s" }}
                    />
                  )}
                </span>
              </div>
            )
          })}
        </div>
      </div>

      {/* Ghost skeleton cards */}
      <div className="rounded-xl border-2 border-border/30 p-5 opacity-30 animate-pulse">
        <div className="flex items-start gap-3">
          <div className="h-10 w-10 rounded-lg bg-muted/60" />
          <div className="flex-1 space-y-2 pt-1">
            <div className="h-3 w-24 rounded bg-muted/80" />
            <div className="h-3 w-full rounded bg-muted/60" />
            <div className="h-3 w-3/4 rounded bg-muted/60" />
          </div>
          <div className="h-8 w-32 rounded-lg bg-muted/60 shrink-0" />
        </div>
        <div className="mt-4 pt-4 border-t border-border/20 space-y-2">
          <div className="h-2.5 w-28 rounded bg-muted/60" />
          <div className="h-3 w-full rounded-full bg-muted/40" />
        </div>
      </div>

      <div className="rounded-xl border border-border/30 p-4 opacity-20 animate-pulse space-y-2">
        {[85, 100, 70, 90, 60].map((w, i) => (
          <div key={i} className="flex items-center gap-3">
            <div className="h-3 w-12 rounded bg-muted/80" />
            <div className="h-3 w-10 rounded bg-muted/60" />
            <div className="h-3 flex-1 rounded bg-muted/50" style={{ maxWidth: `${w}%` }} />
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4 opacity-20 animate-pulse">
        {[0, 1].map((i) => (
          <div key={i} className="rounded-xl border border-border/30 p-4 space-y-2">
            <div className="h-2.5 w-20 rounded bg-muted/80" />
            {[90, 75, 85].map((w, j) => (
              <div key={j} className="h-3 rounded bg-muted/50" style={{ width: `${w}%` }} />
            ))}
          </div>
        ))}
      </div>

      <style>{`
        @keyframes analyst-step-in {
          from { opacity: 0; transform: translateY(3px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  )
}

export default function AnalystReview() {
  const queryClient = useQueryClient()
  const { toast } = useToast()

  const { data, isLoading } = useQuery({
    queryKey: ["analyst-review"],
    queryFn: api.getAnalystReview,
  })

  const requestMutation = useMutation({
    mutationFn: api.requestAnalystReview,
    onSuccess: (review) => {
      queryClient.setQueryData(["analyst-review"], { review })
      toast("success", "Analysis Complete", `Stance: ${review.overall_stance} · Health: ${review.portfolio_health_score}/100`)
    },
    onError: (e: Error) => toast("error", "Analysis Failed", e.message.replace(/^Error:\s*/, "")),
  })

  const applyMutation = useMutation({
    mutationFn: (apply: boolean) => api.applyAnalystReview(apply),
    onSuccess: (result) => {
      queryClient.setQueryData(["analyst-review"], (old: { review: AnalystReviewType } | undefined) =>
        old?.review ? { review: { ...old.review, apply_to_pipeline: result.apply_to_pipeline } } : old
      )
      toast(
        result.apply_to_pipeline ? "success" : "info",
        result.apply_to_pipeline ? "Guidance Applied" : "Guidance Removed",
        result.apply_to_pipeline
          ? "The analyst's guidance will be injected into the next pipeline judge run."
          : "The analyst's guidance will not affect the next pipeline run.",
      )
    },
    onError: (e: Error) => toast("error", "Failed", e.message.replace(/^Error:\s*/, "")),
  })

  const review = data?.review ?? null

  return (
    <>
      <PageHeader
        title="Analyst Review"
        description="On-demand portfolio review by an LLM quantitative analyst"
        actions={
          <div className="flex items-center gap-2">
            {review && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => requestMutation.mutate()}
                disabled={requestMutation.isPending}
                className="text-muted-foreground"
              >
                {requestMutation.isPending
                  ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
                Re-analyse
              </Button>
            )}
            {!review && (
              <Button
                onClick={() => requestMutation.mutate()}
                disabled={requestMutation.isPending}
                className="bg-primary/90 hover:bg-primary"
              >
                {requestMutation.isPending
                  ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  : <BrainCircuit className="mr-2 h-4 w-4" />}
                {requestMutation.isPending ? "Analysing portfolio..." : "Request Analysis"}
              </Button>
            )}
          </div>
        }
      />

      {isLoading && (
        <div className="flex items-center justify-center py-20 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          Loading...
        </div>
      )}

      {requestMutation.isPending && <AnalysisLoadingState />}

      {!isLoading && !requestMutation.isPending && !review && (
        <div className="flex flex-col items-center justify-center py-24 gap-4 text-center">
          <div className="flex items-center justify-center h-16 w-16 rounded-2xl bg-primary/10 border border-primary/20">
            <BrainCircuit className="h-8 w-8 text-primary" />
          </div>
          <div>
            <h3 className="text-lg font-semibold mb-1">No analysis yet</h3>
            <p className="text-sm text-muted-foreground max-w-sm">
              Click "Request Analysis" to get a comprehensive portfolio review from an LLM quantitative analyst.
              The review considers your positions, market conditions, and factor scores.
            </p>
          </div>
          <Button
            onClick={() => requestMutation.mutate()}
            className="bg-primary/90 hover:bg-primary mt-2"
          >
            <BrainCircuit className="mr-2 h-4 w-4" />
            Request Analysis
          </Button>
        </div>
      )}

      {review && !requestMutation.isPending && (
        <ReviewDisplay
          review={review}
          onApplyToggle={() => applyMutation.mutate(!review.apply_to_pipeline)}
          applyPending={applyMutation.isPending}
        />
      )}
    </>
  )
}
