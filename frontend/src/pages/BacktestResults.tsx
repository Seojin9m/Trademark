import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { MetricCard } from "@/components/ui/metric-card"
import { Badge } from "@/components/ui/badge"
import { Terminal } from "lucide-react"

const performanceMetrics = [
  { label: "Annualized Return", value: "15.21%", delta: "+15.21%", deltaValue: 1 },
  { label: "Sharpe Ratio", value: "0.42" },
  { label: "Sortino Ratio", value: "0.60" },
  { label: "Max Drawdown", value: "-32.83%", delta: "-32.83%", deltaValue: -1 },
  { label: "Alpha vs QQQ", value: "+2.14%", delta: "+2.14%", deltaValue: 1 },
  { label: "Information Ratio", value: "0.17" },
]

const tradingMetrics = [
  { label: "Annualized Turnover", value: "139.58%" },
  { label: "Total Trades", value: "340" },
  { label: "Hit Rate", value: "53.81%", delta: "53.81%", deltaValue: 0.5 },
]

const config = {
  rebalance_freq: "2W-FRI (biweekly)",
  min_decile_change: 2,
  max_position_weight: "10%",
  drawdown_alert: "-15%",
  benchmarks: ["QQQ", "XLK"],
}

const factorWeights = [
  { name: "Momentum (12m-1m)", weight: 0.2 },
  { name: "EPS Growth YoY", weight: 0.2 },
  { name: "Revenue Growth YoY", weight: 0.2 },
  { name: "Gross Margin Trend", weight: 0.2 },
  { name: "Relative Valuation", weight: 0.2 },
]

export default function BacktestResults() {
  return (
    <>
      <PageHeader
        title="Backtest Results"
        description="Best results from biweekly equal-weight configuration"
      />

      {/* Performance Metrics */}
      <div className="grid grid-cols-3 gap-4 mb-4">
        {performanceMetrics.map((m) => (
          <MetricCard key={m.label} {...m} />
        ))}
      </div>

      {/* Trading Metrics */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        {tradingMetrics.map((m) => (
          <MetricCard key={m.label} {...m} />
        ))}
      </div>

      <div className="grid grid-cols-2 gap-6 mb-6">
        {/* Factor Weights */}
        <Card>
          <CardTitle>Factor Weights</CardTitle>
          <CardContent>
            <div className="space-y-3">
              {factorWeights.map((f) => (
                <div key={f.name} className="flex items-center gap-3">
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm text-muted-foreground">{f.name}</span>
                      <span className="text-sm font-medium">
                        {(f.weight * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full rounded-full bg-primary/60"
                        style={{ width: `${f.weight * 100}%` }}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Strategy Config */}
        <Card>
          <CardTitle>Strategy Configuration</CardTitle>
          <CardContent>
            <div className="space-y-3">
              {Object.entries(config).map(([key, value]) => (
                <div key={key} className="flex justify-between items-center text-sm">
                  <span className="text-muted-foreground">{key.replace(/_/g, " ")}</span>
                  <span className="font-medium">
                    {Array.isArray(value) ? (
                      <div className="flex gap-1.5">
                        {value.map((v) => (
                          <Badge key={v} variant="muted">{v}</Badge>
                        ))}
                      </div>
                    ) : (
                      String(value)
                    )}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* How to Run */}
      <Card>
        <CardTitle>
          <div className="flex items-center gap-2">
            <Terminal className="h-4 w-4" />
            How to Run
          </div>
        </CardTitle>
        <CardContent>
          <p className="text-sm text-muted-foreground mb-3">
            Run a backtest from the backend directory:
          </p>
          <div className="rounded-lg bg-[#0a0a0f] border border-border/40 px-4 py-3 font-mono text-sm text-foreground/80">
            cd backend && python -c "from src.backtest.engine import run_full_backtest; run_full_backtest()"
          </div>
        </CardContent>
      </Card>
    </>
  )
}
