import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { FactorScore } from "@/lib/api"
import { cn } from "@/lib/utils"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

const FACTORS: Array<{ key: keyof FactorScore; label: string }> = [
  { key: "momentum_12m1m", label: "Momentum" },
  { key: "eps_growth_yoy", label: "EPS" },
  { key: "revenue_growth_yoy", label: "Revenue" },
  { key: "gross_margin_trend", label: "Margin" },
  { key: "relative_valuation", label: "Valuation" },
]

function heatColor(z: number | null): { bg: string; color: string } {
  if (z == null) return { bg: "transparent", color: "var(--color-muted-foreground)" }
  const intensity = Math.min(1, Math.abs(z) / 2.5)
  if (z > 0.1) return {
    bg: `rgba(126, 231, 135, ${0.12 + intensity * 0.45})`,
    color: Math.abs(z) > 1.6 ? "#0a0d0a" : "#e8efe6",
  }
  if (z < -0.1) return {
    bg: `rgba(255, 107, 107, ${0.12 + intensity * 0.45})`,
    color: Math.abs(z) > 1.6 ? "#0a0d0a" : "#e8efe6",
  }
  return { bg: "transparent", color: "#e8efe6" }
}

function fmtSigned(v: number | null, digits = 2): string {
  if (v == null) return "—"
  const sign = v >= 0 ? "+" : ""
  return `${sign}${v.toFixed(digits)}`
}

function pnlText(v: number | null): string {
  if (v == null) return "text-muted-2"
  return v >= 0 ? "text-profit" : "text-loss"
}

function CandidateTable({
  rows,
  variant,
}: {
  rows: FactorScore[]
  variant: "profit" | "loss"
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full font-mono text-[12px] tabular-nums">
        <thead>
          <tr>
            <th className="border-b border-line bg-bg-2 px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">Ticker</th>
            <th className="border-b border-line bg-bg-2 px-3 py-2.5 text-right text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">Composite</th>
            <th className="border-b border-line bg-bg-2 px-3 py-2.5 text-center text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">Decile</th>
            <th className="border-b border-line bg-bg-2 px-3 py-2.5 text-right text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">Momentum</th>
            <th className="border-b border-line bg-bg-2 px-3 py-2.5 text-right text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">EPS</th>
            <th className="border-b border-line bg-bg-2 px-3 py-2.5 text-right text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">Revenue</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.ticker} className="border-b border-line hover:bg-surface-2 transition-colors">
              <td className="px-3 py-1.5 text-foreground font-semibold">{s.ticker}</td>
              <td className={cn("px-3 py-1.5 text-right font-bold", variant === "profit" ? "text-profit" : "text-loss")}>
                {s.composite_score.toFixed(2)}
              </td>
              <td className="px-3 py-1.5 text-center">
                <Badge variant={variant}>{s.score_decile}</Badge>
              </td>
              <td className={cn("px-3 py-1.5 text-right", pnlText(s.momentum_12m1m))}>
                {fmtSigned(s.momentum_12m1m)}
              </td>
              <td className={cn("px-3 py-1.5 text-right", pnlText(s.eps_growth_yoy))}>
                {fmtSigned(s.eps_growth_yoy)}
              </td>
              <td className={cn("px-3 py-1.5 text-right", pnlText(s.revenue_growth_yoy))}>
                {fmtSigned(s.revenue_growth_yoy)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function SignalDashboard() {
  const { data: scores, isLoading, error } = useQuery<FactorScore[]>({
    queryKey: ["scores"],
    queryFn: () => api.getScores(100),
  })

  if (isLoading) {
    return (
      <>
        <PageHeader title="Signal Dashboard" />
        <div className="grid grid-cols-2 gap-4">
          {[0, 1].map((i) => (
            <div key={i} className="h-64 rounded-md border border-line bg-surface animate-shimmer" />
          ))}
        </div>
      </>
    )
  }

  if (error || !scores) {
    return (
      <PageHeader
        title="Signal Dashboard"
        description="Failed to load scores. Run the pipeline first."
      />
    )
  }

  const top10 = scores.slice(0, 10)
  const bottom10 = scores.slice(-10).reverse()
  const scoreDate = scores[0]?.date || "N/A"
  const description = `Most recent scoring · ${scoreDate} · ${scores.length.toLocaleString()} stocks ranked`

  return (
    <>
      <PageHeader title="Signal Dashboard" description={description} />

      <div className="grid grid-cols-2 gap-4 mb-4">
        <Card>
          <CardTitle meta="DECILE 1">Top 10 Buy Candidates</CardTitle>
          <CandidateTable rows={top10} variant="profit" />
        </Card>

        <Card>
          <CardTitle meta="DECILE 9-10">Bottom 10 Sell Candidates</CardTitle>
          <CandidateTable rows={bottom10} variant="loss" />
        </Card>
      </div>

      <Card>
        <CardTitle meta={`${scores.length.toLocaleString()} stocks · z-score`}>
          Factor Heatmap
        </CardTitle>
        <div className="overflow-auto" style={{ maxHeight: 540 }}>
          <table className="w-full font-mono text-[12px] tabular-nums" style={{ minWidth: 720 }}>
            <thead>
              <tr>
                <th className="sticky top-0 z-[1] border-b border-line bg-bg-2 px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground" style={{ width: 80 }}>
                  Ticker
                </th>
                {FACTORS.map((f) => (
                  <th
                    key={f.key}
                    className="sticky top-0 z-[1] border-b border-line bg-bg-2 px-3 py-2.5 text-center text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                  >
                    {f.label}
                  </th>
                ))}
                <th className="sticky top-0 z-[1] border-b border-line bg-bg-2 px-3 py-2.5 text-center text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                  Composite
                </th>
              </tr>
            </thead>
            <tbody>
              {scores.map((s) => (
                <tr key={s.ticker} className="border-b border-line/40">
                  <td className="px-3 py-1.5 text-foreground font-semibold">{s.ticker}</td>
                  {FACTORS.map((f) => {
                    const v = s[f.key] as number | null
                    const { bg, color } = heatColor(v)
                    return (
                      <td
                        key={f.key}
                        className="px-3 py-1.5 text-center border-l border-line"
                        style={{ background: bg, color }}
                      >
                        {fmtSigned(v)}
                      </td>
                    )
                  })}
                  {(() => {
                    const v = s.composite_score
                    const { bg, color } = heatColor(v)
                    return (
                      <td
                        className="px-3 py-1.5 text-center border-l border-line font-semibold"
                        style={{ background: bg, color }}
                      >
                        {fmtSigned(v)}
                      </td>
                    )
                  })()}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}
