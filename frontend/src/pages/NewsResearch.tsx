import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { NewsResearchItem } from "@/lib/api"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { MetricCard } from "@/components/ui/metric-card"
import {
  Zap,
  Newspaper,
} from "lucide-react"
import { cn } from "@/lib/utils"

function sentimentVariant(s: string): "profit" | "loss" | "warn" | "muted" {
  switch (s) {
    case "positive": return "profit"
    case "negative": return "loss"
    case "mixed": return "warn"
    default: return "muted"
  }
}

function ResearchCard({ research }: { research: NewsResearchItem }) {
  const headlines = typeof research.headlines === "string"
    ? JSON.parse(research.headlines)
    : research.headlines || []
  const binaryEvents = typeof research.binary_events === "string"
    ? JSON.parse(research.binary_events)
    : research.binary_events || []
  const riskFactors = typeof research.risk_factors === "string"
    ? JSON.parse(research.risk_factors)
    : research.risk_factors || []
  const opportunities = typeof research.opportunities === "string"
    ? JSON.parse(research.opportunities)
    : research.opportunities || []

  return (
    <Card>
      <div className="px-6 pt-5 pb-5">
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <span className="text-lg font-semibold">{research.ticker}</span>
            <Badge variant={sentimentVariant(research.sentiment)}>
              {research.sentiment}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {Math.round(research.confidence * 100)}% confidence
            </span>
          </div>
          <span className="text-xs text-muted-foreground">{research.research_date}</span>
        </div>

        {/* AI Summary */}
        {research.ai_summary && research.ai_summary !== "No recent news found." && (
          <p className="text-sm text-foreground/80 mb-4 leading-relaxed">
            {research.ai_summary}
          </p>
        )}

        {/* Binary Events */}
        {binaryEvents.length > 0 && (
          <div className="mb-3">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
              Binary Events
            </p>
            <div className="space-y-1.5">
              {binaryEvents.map((e: { event_type: string; description: string; expected_date: string | null; potential_impact: string }, i: number) => (
                <div key={i} className="flex items-center gap-2 text-sm">
                  <Zap className={cn(
                    "h-3.5 w-3.5 shrink-0",
                    e.potential_impact === "high" ? "text-loss" : e.potential_impact === "medium" ? "text-warn" : "text-muted-foreground",
                  )} />
                  <Badge variant={e.potential_impact === "high" ? "loss" : e.potential_impact === "medium" ? "warn" : "muted"}>
                    {e.event_type}
                  </Badge>
                  <span className="text-foreground/70">{e.description}</span>
                  {e.expected_date && (
                    <span className="text-xs text-muted-foreground ml-auto">{e.expected_date}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Risk & Opportunities grid */}
        {(riskFactors.length > 0 || opportunities.length > 0) && (
          <div className="grid grid-cols-2 gap-4 mt-3">
            {riskFactors.length > 0 && (
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-loss/70 mb-1.5">
                  Risk Factors
                </p>
                <ul className="space-y-1">
                  {riskFactors.map((r: string, i: number) => (
                    <li key={i} className="text-xs text-foreground/60 flex items-start gap-1.5">
                      <span className="text-loss mt-0.5">-</span>
                      {r}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {opportunities.length > 0 && (
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-profit/70 mb-1.5">
                  Opportunities
                </p>
                <ul className="space-y-1">
                  {opportunities.map((o: string, i: number) => (
                    <li key={i} className="text-xs text-foreground/60 flex items-start gap-1.5">
                      <span className="text-profit mt-0.5">+</span>
                      {o}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Headlines */}
        {headlines.length > 0 && (
          <div className="mt-4 pt-3 border-t border-border/40">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
              Headlines ({headlines.length})
            </p>
            <div className="space-y-1">
              {headlines.slice(0, 5).map((h: string, i: number) => (
                <p key={i} className="text-xs text-muted-foreground truncate">
                  {h}
                </p>
              ))}
              {headlines.length > 5 && (
                <p className="text-xs text-muted-foreground/50">
                  +{headlines.length - 5} more
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}

export default function NewsResearch() {
  const { data: research, isLoading } = useQuery<NewsResearchItem[]>({
    queryKey: ["research"],
    queryFn: () => api.getResearch(),
  })

  if (isLoading) {
    return (
      <>
        <PageHeader title="News Research" />
        <div className="space-y-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-40 rounded-xl border border-border/60 bg-card animate-shimmer" />
          ))}
        </div>
      </>
    )
  }

  const all = research || []
  const withNews = all.filter((r) => r.confidence > 0)
  const positive = all.filter((r) => r.sentiment === "positive").length
  const negative = all.filter((r) => r.sentiment === "negative").length
  const binaryTotal = all.reduce((sum, r) => {
    const events = typeof r.binary_events === "string"
      ? JSON.parse(r.binary_events)
      : r.binary_events || []
    return sum + events.length
  }, 0)

  return (
    <>
      <PageHeader
        title="News Research"
        description="AI-powered news analysis for portfolio tickers"
      />

      <div className="grid grid-cols-4 gap-4 mb-6">
        <MetricCard label="Tickers Researched" value={String(all.length)} />
        <MetricCard label="With News" value={String(withNews.length)} />
        <MetricCard
          label="Sentiment"
          value={positive > negative ? "Mostly Positive" : negative > positive ? "Mostly Negative" : "Mixed"}
        />
        <MetricCard label="Binary Events" value={String(binaryTotal)} />
      </div>

      {all.length === 0 ? (
        <Card>
          <CardContent>
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Newspaper className="h-10 w-10 text-muted-foreground/30 mb-3" />
              <p className="text-sm text-muted-foreground">
                No research data yet. Run the pipeline to generate news research.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {all.map((r) => (
            <ResearchCard key={r.ticker} research={r} />
          ))}
        </div>
      )}
    </>
  )
}
