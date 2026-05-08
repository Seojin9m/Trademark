import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useState, useEffect, useRef } from "react"
import { api } from "@/lib/api"
import type { AnalystReview as AnalystReviewType } from "@/lib/api"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { SectionTitle } from "@/components/ui/section-title"
import { useToast } from "@/contexts/toast-context"
import { useAnalyst } from "@/contexts/analyst-context"
import { cn } from "@/lib/utils"
import {
  Loader2, BrainCircuit, TrendingUp, TrendingDown, Minus, Play, RefreshCw,
} from "lucide-react"

const STANCE_CONFIG = {
  bullish: { label: "BULLISH", variant: "profit" as const, icon: TrendingUp },
  neutral: { label: "NEUTRAL", variant: "muted" as const, icon: Minus },
  bearish: { label: "BEARISH", variant: "loss" as const, icon: TrendingDown },
}

const POSITION_BADGE_VARIANT: Record<"add" | "hold" | "trim" | "exit", "profit" | "warn" | "loss" | "default"> = {
  add: "profit",
  hold: "default",
  trim: "warn",
  exit: "loss",
}

const ANALYSIS_GROUP_VARIANT: Record<string, "profit" | "warn" | "accent" | "loss"> = {
  Strengths: "profit",
  Concerns: "warn",
  Opportunities: "accent",
  "Risk Factors": "loss",
}

function ToggleSwitch({ on, onClick, disabled }: { on: boolean; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "relative h-[18px] w-[32px] rounded-full border border-line-2 transition-colors disabled:opacity-50",
        on ? "bg-primary" : "bg-bg-2",
      )}
      aria-pressed={on}
    >
      <span
        className={cn(
          "absolute top-px h-[14px] w-[14px] rounded-full transition-all",
          on ? "left-[15px] bg-background" : "left-px bg-muted-foreground",
        )}
      />
    </button>
  )
}

function HealthGauge({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, score))
  return (
    <div className="relative h-1.5 rounded-[3px] bg-line">
      <div
        className="absolute inset-y-0 left-0 rounded-[3px]"
        style={{
          width: `${pct}%`,
          background: "linear-gradient(90deg, var(--color-loss), var(--color-warn), var(--color-profit))",
          backgroundSize: `${100 / Math.max(pct, 1) * 100}% 100%`,
        }}
      />
      <div
        className="absolute -top-[3px] w-[2px] h-[12px] bg-foreground"
        style={{ left: `calc(${pct}% - 1px)` }}
      />
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

  // Format generated_at like "Generated 2026-05-03 16:42 ET"
  const generatedAt = (() => {
    const d = new Date(review.created_at)
    const yyyy = d.getFullYear()
    const mm = String(d.getMonth() + 1).padStart(2, "0")
    const dd = String(d.getDate()).padStart(2, "0")
    const hh = String(d.getHours()).padStart(2, "0")
    const mi = String(d.getMinutes()).padStart(2, "0")
    return `Generated ${yyyy}-${mm}-${dd} ${hh}:${mi}`
  })()

  const groups = [
    { title: "Strengths", items: review.strengths },
    { title: "Concerns", items: review.concerns },
    { title: "Opportunities", items: review.opportunities },
    { title: "Risk Factors", items: review.risk_factors },
  ]

  return (
    <div className="space-y-4">
      {/* Header card — flush, two-column: summary + health/toggle */}
      <Card>
        <div className="flex items-start gap-5 p-[18px]">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2.5 mb-2">
              <Badge variant={cfg.variant}>
                <StanceIcon className="h-2.5 w-2.5" />
                {cfg.label}
              </Badge>
              <span className="font-mono text-[11px] text-muted-2">{generatedAt}</span>
            </div>
            <p className="text-[13.5px] leading-[1.6] text-foreground/90 max-w-[880px]">
              {review.summary}
            </p>
          </div>

          <div className="w-[200px] shrink-0">
            <div className="font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
              Portfolio Health
            </div>
            <div className="font-mono text-[22px] font-medium text-primary mb-1.5 tabular-nums">
              {review.portfolio_health_score}
              <span className="text-[13px] text-muted-foreground"> / 100</span>
            </div>
            <HealthGauge score={review.portfolio_health_score} />
            <div className="flex items-center mt-3 font-mono text-[11px] text-muted-foreground">
              <span>Apply to pipeline</span>
              <span className="ml-auto">
                <ToggleSwitch on={review.apply_to_pipeline} onClick={onApplyToggle} disabled={applyPending} />
              </span>
            </div>
          </div>
        </div>
      </Card>

      {/* Market context */}
      {review.market_context && (
        <Card>
          <CardTitle>Market Context</CardTitle>
          <CardContent>
            <p className="text-[13px] leading-[1.65] text-fg-dim max-w-[880px]">
              {review.market_context}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Position Assessment */}
      {review.position_reviews?.length > 0 && (
        <>
          <SectionTitle meta={`${review.position_reviews.length} POSITIONS`}>
            Position Assessment
          </SectionTitle>
          <Card>
            {review.position_reviews.map((pr, i) => (
              <div
                key={pr.ticker}
                className={cn(
                  "grid items-center gap-[14px] px-4 py-[11px]",
                  i < review.position_reviews.length - 1 && "border-b border-line",
                )}
                style={{ gridTemplateColumns: "70px 90px 1fr 80px" }}
              >
                <span className="font-mono text-[13px] font-semibold text-foreground">
                  {pr.ticker}
                </span>
                <Badge variant={POSITION_BADGE_VARIANT[pr.stance]}>
                  {pr.stance.toUpperCase()}
                </Badge>
                <span className="text-[12.5px] leading-[1.5] text-fg-dim">
                  {pr.reasoning}
                </span>
                <div className="text-right">
                  <div className="font-mono text-[12px] font-semibold text-foreground tabular-nums">
                    {Math.round(pr.conviction * 100)}%
                  </div>
                  <div className="relative h-1 w-[70px] ml-auto mt-[3px] rounded-[2px] bg-line overflow-hidden">
                    <div
                      className="absolute inset-y-0 left-0 bg-primary rounded-[2px]"
                      style={{ width: `${pr.conviction * 100}%` }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </Card>
        </>
      )}

      {/* Analysis Grid */}
      {groups.some((g) => g.items?.length > 0) && (
        <>
          <SectionTitle>Analysis Grid</SectionTitle>
          <div className="grid grid-cols-2 gap-4">
            {groups.map((grp) => {
              if (!grp.items?.length) return null
              const variant = ANALYSIS_GROUP_VARIANT[grp.title]
              return (
                <Card key={grp.title}>
                  <CardTitle
                    action={<Badge variant={variant}>{grp.items.length}</Badge>}
                  >
                    {grp.title}
                  </CardTitle>
                  <CardContent>
                    <div className="flex flex-col gap-2">
                      {grp.items.map((item, i) => {
                        const dashIdx = item.indexOf(" — ")
                        const headline = dashIdx > -1 ? item.slice(0, dashIdx) : null
                        const detail = dashIdx > -1 ? item.slice(dashIdx + 3) : item
                        return (
                          <div
                            key={i}
                            className="flex gap-2.5 p-2.5 rounded-[4px] border border-line bg-bg-2"
                          >
                            <span
                              className={cn(
                                "shrink-0 mt-[3px] h-[6px] w-[6px] rounded-full",
                                variant === "profit" && "bg-profit",
                                variant === "warn" && "bg-warn",
                                variant === "accent" && "bg-primary",
                                variant === "loss" && "bg-loss",
                              )}
                            />
                            <div className="min-w-0">
                              {headline && (
                                <div className="text-[12.5px] font-semibold text-foreground mb-0.5">
                                  {headline}
                                </div>
                              )}
                              <div className="text-[11.5px] leading-[1.5] text-muted-foreground">
                                {detail}
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        </>
      )}

      {/* Pipeline Guidance — numbered list */}
      {review.pipeline_guidance?.length > 0 && (
        <Card>
          <CardTitle
            meta={review.apply_to_pipeline ? "Next pipeline run will inject these instructions" : undefined}
            action={review.apply_to_pipeline ? <Badge variant="accent">ACTIVE</Badge> : undefined}
          >
            Pipeline Guidance
          </CardTitle>
          <CardContent>
            <div className="flex flex-col gap-1.5 text-[12.5px] text-fg-dim">
              {review.pipeline_guidance.map((g, i) => (
                <div
                  key={i}
                  className="flex gap-2.5 p-2.5 rounded-[4px] border border-line bg-bg-2"
                >
                  <span className="font-mono text-primary min-w-[24px]">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span>{g}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

const THINKING_STEPS = [
  "Loading portfolio positions",
  "Fetching factor scores from latest run",
  "Computing factor exposures and concentrations",
  "Analyzing sector and style tilts",
  "Cross-referencing news sentiment (last 7d)",
  "Stress-testing against macro scenarios",
  "Identifying strengths and concerns",
  "Generating per-position recommendations",
  "Drafting market context narrative",
  "Finalizing review",
]

function AnalysisLoadingState() {
  const { visibleSteps } = useAnalyst()
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [visibleSteps])

  const visibleCount = Math.min(visibleSteps, THINKING_STEPS.length)

  return (
    <div className="space-y-4">
      <Card>
        <CardTitle meta={`STEP ${Math.min(visibleCount, THINKING_STEPS.length)} / ${THINKING_STEPS.length}`}>
          Analysis In Progress
        </CardTitle>
        <CardContent>
          <div
            ref={logRef}
            className="rounded-md border border-line bg-[#050706] font-mono text-[11.5px] text-fg-dim p-[14px_16px] max-h-[400px] overflow-y-auto"
          >
            {THINKING_STEPS.slice(0, visibleCount).map((step, i) => {
              const isLast = i === visibleCount - 1
              const isDone = i < visibleCount - 1
              return (
                <div key={i} className="flex gap-2.5 items-start">
                  <span className="text-muted-2 w-6 text-right shrink-0">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className={cn("w-[14px] shrink-0", isDone ? "text-profit" : "text-primary")}>
                    {isDone ? "✓" : "▶"}
                  </span>
                  <span className="text-primary font-semibold shrink-0 min-w-[90px]">
                    [analyst]
                  </span>
                  <span className="flex-1">
                    {step}
                    {isLast && (
                      <span className="inline-block w-[7px] h-[12px] bg-primary align-[-2px] ml-1 animate-blink" />
                    )}
                  </span>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-4">
        <div className="h-[200px] rounded-md border border-line bg-surface animate-shimmer" />
        <div className="h-[200px] rounded-md border border-line bg-surface animate-shimmer" />
      </div>
    </div>
  )
}

export default function AnalystReview() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { analyzing, requestAnalysis } = useAnalyst()
  const [isLoaded, setIsLoaded] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ["analyst-review"],
    queryFn: api.getAnalystReview,
  })

  useEffect(() => {
    if (!isLoading) setIsLoaded(true)
  }, [isLoading])

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
          <Button
            variant="primary"
            size="sm"
            onClick={requestAnalysis}
            disabled={analyzing}
          >
            {analyzing ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Analyzing…
              </>
            ) : review ? (
              <>
                <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
                Re-analyse
              </>
            ) : (
              <>
                <Play className="mr-1.5 h-3.5 w-3.5" />
                Request Analysis
              </>
            )}
          </Button>
        }
      />

      {!isLoaded && (
        <div className="flex items-center justify-center py-20 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          Loading...
        </div>
      )}

      {analyzing && <AnalysisLoadingState />}

      {isLoaded && !analyzing && !review && (
        <div className="flex flex-col items-center justify-center py-24 gap-4 text-center">
          <div className="flex items-center justify-center h-16 w-16 rounded-2xl bg-primary/10 border border-primary/20">
            <BrainCircuit className="h-8 w-8 text-primary" />
          </div>
          <div>
            <h3 className="text-lg font-semibold mb-1">No analysis yet</h3>
            <p className="text-sm text-muted-foreground max-w-sm">
              Click "Request Analysis" to get a comprehensive portfolio review from an LLM quantitative analyst.
            </p>
          </div>
        </div>
      )}

      {review && !analyzing && (
        <ReviewDisplay
          review={review}
          onApplyToggle={() => applyMutation.mutate(!review.apply_to_pipeline)}
          applyPending={applyMutation.isPending}
        />
      )}
    </>
  )
}
