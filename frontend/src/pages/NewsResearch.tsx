import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { NewsResearchItem, BinaryEvent } from "@/lib/api"
import { PageHeader } from "@/components/layout/page-header"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { MetricCard } from "@/components/ui/metric-card"
import { SectionTitle } from "@/components/ui/section-title"
import { TrendingUp, TrendingDown, Minus, Newspaper } from "lucide-react"

type SentimentVariant = "profit" | "loss" | "warn" | "muted"

function sentimentVariant(s: string): SentimentVariant {
  const k = s.toLowerCase()
  if (k === "positive" || k === "bullish") return "profit"
  if (k === "negative" || k === "bearish") return "loss"
  if (k === "mixed" || k === "neutral") return "warn"
  return "muted"
}

function sentimentIcon(s: string) {
  const k = s.toLowerCase()
  if (k === "positive" || k === "bullish") return TrendingUp
  if (k === "negative" || k === "bearish") return TrendingDown
  return Minus
}

function impactVariant(impact: string): SentimentVariant {
  const k = impact.toLowerCase()
  if (k === "high") return "loss"
  if (k === "medium") return "warn"
  return "muted"
}

function parseList<T>(value: string | T[] | undefined): T[] {
  if (!value) return []
  if (Array.isArray(value)) return value
  try {
    return JSON.parse(value) as T[]
  } catch {
    return []
  }
}

function ResearchCard({ research }: { research: NewsResearchItem }) {
  const headlines = parseList<string>(research.headlines)
  const binaryEvents = parseList<BinaryEvent>(research.binary_events)
  const riskFactors = parseList<string>(research.risk_factors)
  const opportunities = parseList<string>(research.opportunities)
  const sources = parseList<string>(research.data_sources)

  const SIcon = sentimentIcon(research.sentiment)
  const sentimentLabel = research.sentiment.toUpperCase()
  const summary = research.ai_summary && research.ai_summary !== "No recent news found."
    ? research.ai_summary
    : null

  return (
    <Card>
      {/* Header row */}
      <div className="flex items-center gap-3.5 px-[18px] py-[14px] border-b border-line">
        <span className="font-mono text-[18px] font-semibold text-foreground">
          {research.ticker}
        </span>
        <Badge variant={sentimentVariant(research.sentiment)}>
          <SIcon className="h-2.5 w-2.5" />
          {sentimentLabel}
        </Badge>
        <span className="font-mono text-[11px] text-muted-2">
          Confidence {Math.round(research.confidence * 100)}%
        </span>
        <span className="flex-1" />
        <span className="font-mono text-[11px] text-muted-2">
          Synthesized {research.research_date}
        </span>
      </div>

      {/* Body */}
      <div className="px-[18px] py-[18px]">
        {summary && (
          <p className="text-[13px] leading-[1.65] text-fg-dim">
            {summary}
          </p>
        )}

        {binaryEvents.length > 0 && (
          <>
            <SectionTitle>Binary Events</SectionTitle>
            <div className="flex flex-col gap-1.5">
              {binaryEvents.map((e, i) => (
                <div
                  key={i}
                  className="grid items-center gap-2.5 p-2.5 rounded-[4px] border border-line bg-bg-2"
                  style={{ gridTemplateColumns: "110px 1fr 100px 80px" }}
                >
                  <Badge variant="default">{e.event_type.toUpperCase()}</Badge>
                  <span className="text-[12.5px] text-foreground">{e.description}</span>
                  <span className="font-mono text-[11.5px] text-muted-2">
                    {e.expected_date || "—"}
                  </span>
                  <Badge variant={impactVariant(e.potential_impact)}>
                    {e.potential_impact.toUpperCase()}
                  </Badge>
                </div>
              ))}
            </div>
          </>
        )}

        {(riskFactors.length > 0 || opportunities.length > 0) && (
          <div className="grid grid-cols-2 gap-[18px] mt-[14px]">
            {riskFactors.length > 0 && (
              <div>
                <div className="font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] text-loss mb-2">
                  Risk Factors
                </div>
                <ul className="m-0 pl-[18px] text-[12.5px] text-fg-dim leading-[1.8] list-disc">
                  {riskFactors.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            )}
            {opportunities.length > 0 && (
              <div>
                <div className="font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] text-profit mb-2">
                  Opportunities
                </div>
                <ul className="m-0 pl-[18px] text-[12.5px] text-fg-dim leading-[1.8] list-disc">
                  {opportunities.map((o, i) => (
                    <li key={i}>{o}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {headlines.length > 0 && (
          <>
            <SectionTitle meta={`${headlines.length} total`}>Headlines</SectionTitle>
            <ul className="m-0 pl-[18px] text-[12.5px] text-muted-foreground leading-[1.7] list-disc">
              {headlines.slice(0, 5).map((h, i) => (
                <li key={i} className="truncate">{h}</li>
              ))}
              {headlines.length > 5 && (
                <li className="list-none text-muted-2 mt-1">
                  +{headlines.length - 5} more
                </li>
              )}
            </ul>
          </>
        )}

        {sources.length > 0 && (
          <div className="mt-3 pt-3 border-t border-line/40 flex items-center gap-1.5 flex-wrap font-mono text-[10.5px] text-muted-2">
            <span className="uppercase tracking-[0.08em] mr-1">Sources:</span>
            {sources.map((s, i) => (
              <span key={i}>
                {s}
                {i < sources.length - 1 && <span className="text-muted-2/60"> · </span>}
              </span>
            ))}
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

  const all = research || []

  if (isLoading) {
    return (
      <>
        <PageHeader title="News Research" />
        <div className="grid grid-cols-4 gap-4 mb-[18px]">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-24 rounded-md border border-line bg-surface animate-shimmer" />
          ))}
        </div>
        <div className="space-y-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-40 rounded-md border border-line bg-surface animate-shimmer" />
          ))}
        </div>
      </>
    )
  }

  // Aggregate stats for the metric row
  const withNews = all.filter((r) => r.confidence > 0)
  const positive = all.filter((r) => sentimentVariant(r.sentiment) === "profit").length
  const negative = all.filter((r) => sentimentVariant(r.sentiment) === "loss").length
  const binaryTotal = all.reduce((sum, r) => sum + parseList<BinaryEvent>(r.binary_events).length, 0)

  // Description: count distinct sources across all tickers
  const allSources = new Set<string>()
  for (const r of all) {
    for (const s of parseList<string>(r.data_sources)) {
      allSources.add(s)
    }
  }
  const sourceCount = allSources.size
  const description = all.length > 0
    ? `LLM-synthesized context per holding · ${all.length} ticker${all.length === 1 ? "" : "s"}${sourceCount > 0 ? ` · ${sourceCount} source${sourceCount === 1 ? "" : "s"}` : ""}`
    : "LLM-synthesized news analysis for portfolio tickers"

  const sentimentLabel =
    positive > negative ? "Mostly Positive"
    : negative > positive ? "Mostly Negative"
    : "Mixed"

  return (
    <>
      <PageHeader title="News Research" description={description} />

      <div className="grid grid-cols-4 gap-4 mb-[18px]">
        <MetricCard
          accent
          label="Tickers Researched"
          value={String(all.length)}
          sub={`${withNews.length} with active news`}
        />
        <MetricCard
          label="Positive"
          value={String(positive)}
          sub={positive === 1 ? "ticker bullish" : "tickers bullish"}
        />
        <MetricCard
          label="Negative"
          value={String(negative)}
          sub={negative === 1 ? "ticker bearish" : "tickers bearish"}
        />
        <MetricCard
          label="Binary Events"
          value={String(binaryTotal)}
          sub={sentimentLabel}
        />
      </div>

      {all.length === 0 ? (
        <Card>
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <Newspaper className="h-10 w-10 text-muted-foreground/30 mb-3" />
            <p className="text-sm text-muted-foreground">
              No research data yet. Run the pipeline to generate news research.
            </p>
          </div>
        </Card>
      ) : (
        <div className="flex flex-col gap-[14px]">
          {all.map((r) => (
            <ResearchCard key={r.ticker} research={r} />
          ))}
        </div>
      )}
    </>
  )
}
