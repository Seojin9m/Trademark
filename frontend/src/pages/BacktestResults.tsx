import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { MetricCard } from "@/components/ui/metric-card"
import { Badge } from "@/components/ui/badge"
import { SectionTitle } from "@/components/ui/section-title"
import { Terminal } from "lucide-react"
import { cn } from "@/lib/utils"

type MetricSign = "profit" | "loss" | "neutral"

interface MetricSpec {
  label: string
  value: string
  sub?: string
  sign?: MetricSign
  accent?: boolean
}

const performanceMetrics: MetricSpec[] = [
  { label: "Annualized Return", value: "15.21%", sub: "vs QQQ 13.85%", sign: "profit", accent: true },
  { label: "Sharpe Ratio", value: "0.42", sub: "risk-adjusted return" },
  { label: "Sortino Ratio", value: "0.60", sub: "downside-adjusted" },
  { label: "Max Drawdown", value: "-32.83%", sub: "peak-to-trough", sign: "loss" },
  { label: "Alpha vs QQQ", value: "+2.14%", sub: "annualized excess", sign: "profit" },
  { label: "Information Ratio", value: "0.17", sub: "tracking error 12.3%" },
]

const tradingMetrics: MetricSpec[] = [
  { label: "Annualized Turnover", value: "139.58%", sub: "position-weighted" },
  { label: "Total Trades", value: "340", sub: "across backtest" },
  { label: "Hit Rate", value: "53.81%", sub: "winners / total", sign: "profit" },
]

const factorWeights = [
  { name: "Momentum (12m-1m)", weight: 0.2 },
  { name: "EPS Growth YoY", weight: 0.2 },
  { name: "Revenue Growth YoY", weight: 0.2 },
  { name: "Gross Margin Trend", weight: 0.2 },
  { name: "Relative Valuation", weight: 0.2 },
]

const strategyConfig: Array<[string, string | string[]]> = [
  ["Rebalance frequency", "Biweekly (2W-FRI)"],
  ["Min decile change", "2 deciles"],
  ["Max position weight", "10%"],
  ["Drawdown alert", "-15%"],
  ["Universe", "S&P 500 + Russell 2000 top quintile"],
  ["Benchmarks", ["QQQ", "XLK"]],
]

function MetricCardRendered({ spec }: { spec: MetricSpec }) {
  if (!spec.sign || spec.sign === "neutral") {
    return (
      <MetricCard
        accent={spec.accent}
        label={spec.label}
        value={spec.value}
        sub={spec.sub}
      />
    )
  }
  return (
    <MetricCard
      accent={spec.accent}
      label={spec.label}
      value={spec.value}
      valueNode={
        <span className={cn(spec.sign === "profit" ? "text-profit" : "text-loss")}>
          {spec.value}
        </span>
      }
      sub={spec.sub}
    />
  )
}

export default function BacktestResults() {
  return (
    <>
      <PageHeader
        title="Backtest Results"
        description="Configuration: biweekly rebal · S&P 500 + Russell 2000 universe · benchmarks QQQ / XLK"
      />

      <SectionTitle>Performance Metrics</SectionTitle>
      <div className="grid grid-cols-3 gap-4 mb-[14px]">
        {performanceMetrics.map((m) => (
          <MetricCardRendered key={m.label} spec={m} />
        ))}
      </div>

      <SectionTitle>Trading Metrics</SectionTitle>
      <div className="grid grid-cols-3 gap-4 mb-[14px]">
        {tradingMetrics.map((m) => (
          <MetricCardRendered key={m.label} spec={m} />
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4 mb-4">
        <Card>
          <CardTitle>Factor Weights</CardTitle>
          <CardContent>
            <div className="flex flex-col gap-3">
              {factorWeights.map((f) => (
                <div key={f.name}>
                  <div className="flex font-mono text-[12px] mb-1">
                    <span className="flex-1 text-foreground">{f.name}</span>
                    <span className="font-semibold text-primary tabular-nums">
                      {(f.weight * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="h-1.5 rounded-[3px] bg-line overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-[3px]"
                      style={{ width: `${Math.min(100, f.weight * 100 * 3)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardTitle>Strategy Configuration</CardTitle>
          <CardContent>
            <div className="flex flex-col font-mono text-[12px]">
              {strategyConfig.map(([label, value], i) => (
                <div
                  key={label}
                  className={cn(
                    "flex items-center gap-3 py-2",
                    i < strategyConfig.length - 1 && "border-b border-dashed border-line",
                  )}
                >
                  <span className="flex-1 text-muted-foreground">{label}</span>
                  {Array.isArray(value) ? (
                    <div className="flex gap-1.5">
                      {value.map((v) => (
                        <Badge key={v} variant="accent">{v}</Badge>
                      ))}
                    </div>
                  ) : (
                    <span className="font-semibold text-primary text-right">{value}</span>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardTitle>
          <span className="inline-flex items-center gap-1.5">
            <Terminal className="h-3.5 w-3.5" />
            How to Run
          </span>
        </CardTitle>
        <CardContent>
          <p className="text-[12.5px] text-fg-dim mb-3 leading-[1.5]">
            Run a backtest from the backend directory:
          </p>
          <div className="rounded-[4px] bg-[#050706] border border-line px-4 py-3 font-mono text-[12px] text-fg-dim leading-[1.6]">
            cd backend &amp;&amp; python -c "from src.backtest.engine import run_full_backtest; run_full_backtest()"
          </div>
        </CardContent>
      </Card>
    </>
  )
}
