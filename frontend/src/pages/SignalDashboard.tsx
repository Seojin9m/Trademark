import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { FactorScore } from "@/lib/api"
import { formatNumber, cn } from "@/lib/utils"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { DataTable } from "@/components/ui/data-table"

function factorColor(val: number | null): string {
  if (val == null) return "bg-muted/50"
  if (val > 1) return "bg-profit/40 text-profit"
  if (val > 0.5) return "bg-profit/20 text-profit"
  if (val > -0.5) return "bg-muted/50 text-foreground"
  if (val > -1) return "bg-loss/20 text-loss"
  return "bg-loss/40 text-loss"
}

function FactorCell({ val }: { val: number | null }) {
  return (
    <span className={cn("inline-block w-14 rounded-md px-1.5 py-0.5 text-center text-xs", factorColor(val))}>
      {val != null ? formatNumber(val, 2) : "-"}
    </span>
  )
}

const scoreColumns = (variant: "profit" | "loss") => [
  {
    key: "ticker",
    header: "Ticker",
    render: (s: FactorScore) => <span className="font-semibold">{s.ticker}</span>,
  },
  {
    key: "score",
    header: "Score",
    align: "right" as const,
    render: (s: FactorScore) => <span>{formatNumber(s.composite_score, 3)}</span>,
  },
  {
    key: "decile",
    header: "Decile",
    align: "right" as const,
    render: (s: FactorScore) => <Badge variant={variant}>{s.score_decile}</Badge>,
  },
  {
    key: "mom",
    header: "Mom",
    align: "right" as const,
    render: (s: FactorScore) => <FactorCell val={s.momentum_12m1m} />,
  },
  {
    key: "eps",
    header: "EPS",
    align: "right" as const,
    render: (s: FactorScore) => <FactorCell val={s.eps_growth_yoy} />,
  },
  {
    key: "rev",
    header: "Rev",
    align: "right" as const,
    render: (s: FactorScore) => <FactorCell val={s.revenue_growth_yoy} />,
  },
]

export default function SignalDashboard() {
  const { data: scores, isLoading, error } = useQuery<FactorScore[]>({
    queryKey: ["scores"],
    queryFn: () => api.getScores(100),
  })

  if (isLoading) {
    return (
      <>
        <PageHeader title="Signal Dashboard" />
        <div className="grid grid-cols-2 gap-6">
          {[0, 1].map((i) => (
            <div key={i} className="h-64 rounded-xl border border-border/60 bg-card animate-shimmer" />
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

  return (
    <>
      <PageHeader title="Signal Dashboard" description={`Scores as of ${scoreDate}`} />

      <div className="grid grid-cols-2 gap-6 mb-8">
        <Card>
          <CardTitle>Top 10 - Buy Candidates</CardTitle>
          <CardContent>
            <DataTable
              columns={scoreColumns("profit")}
              data={top10}
              rowKey={(s) => s.ticker}
              compact
            />
          </CardContent>
        </Card>

        <Card>
          <CardTitle>Bottom 10 - Sell Candidates</CardTitle>
          <CardContent>
            <DataTable
              columns={scoreColumns("loss")}
              data={bottom10}
              rowKey={(s) => s.ticker}
              compact
            />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardTitle>Factor Heatmap</CardTitle>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border/60">
                  <th className="pb-3 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground w-20">
                    Ticker
                  </th>
                  {["Momentum", "EPS Growth", "Rev Growth", "Margin", "Valuation"].map((h) => (
                    <th key={h} className="pb-3 text-center text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      {h}
                    </th>
                  ))}
                  <th className="pb-3 text-right text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Composite
                  </th>
                </tr>
              </thead>
              <tbody>
                {scores.map((s) => (
                  <tr key={s.ticker} className="border-b border-border/20 hover:bg-accent/20 transition-colors">
                    <td className="py-1.5 font-medium text-sm">{s.ticker}</td>
                    {[
                      s.momentum_12m1m,
                      s.eps_growth_yoy,
                      s.revenue_growth_yoy,
                      s.gross_margin_trend,
                      s.relative_valuation,
                    ].map((val, i) => (
                      <td key={i} className="py-1.5 text-center">
                        <FactorCell val={val} />
                      </td>
                    ))}
                    <td className="py-1.5 text-right font-medium text-sm">
                      {formatNumber(s.composite_score, 3)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </>
  )
}
