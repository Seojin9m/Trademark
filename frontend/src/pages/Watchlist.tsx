import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { useToast } from "@/contexts/toast-context"
import {
  Plus, Trash2, Star, Loader2, Search,
  TrendingUp, TrendingDown, Minus, Calendar,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { api, type WatchlistItem, type TickerAnalysis } from "@/lib/api"

function sentimentBadge(sentiment?: string) {
  if (!sentiment) return null
  const colors: Record<string, string> = {
    positive: "bg-profit/20 text-profit border-profit/30",
    negative: "bg-loss/20 text-loss border-loss/30",
    neutral: "bg-muted/40 text-muted-foreground border-border/40",
    mixed: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  }
  return (
    <Badge variant="default" className={cn("text-[10px]", colors[sentiment] ?? colors.neutral)}>
      {sentiment}
    </Badge>
  )
}

function earningsCountdown(item: WatchlistItem) {
  const e = item.upcoming_earnings
  if (!e) return null
  const days = e.days_until
  const color = days <= 3 ? "text-loss" : days <= 7 ? "text-amber-400" : "text-profit"
  return (
    <div className={cn("flex items-center gap-1 text-xs", color)}>
      <Calendar className="h-3 w-3" />
      <span>{days}d</span>
    </div>
  )
}

export default function Watchlist() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [addTicker, setAddTicker] = useState("")
  const [analysisResult, setAnalysisResult] = useState<TickerAnalysis | null>(null)
  const [analyzingTicker, setAnalyzingTicker] = useState<string | null>(null)

  const { data: watchlist, isLoading } = useQuery({
    queryKey: ["watchlist"],
    queryFn: api.getWatchlist,
    refetchInterval: 30_000,
  })

  const addMutation = useMutation({
    mutationFn: (ticker: string) => api.addToWatchlist(ticker),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["watchlist"] })
      setAddTicker("")
      toast("success", "Added", `${addTicker} added to watchlist`)
    },
    onError: (e) => toast("error", "Failed", String(e)),
  })

  const removeMutation = useMutation({
    mutationFn: (ticker: string) => api.removeFromWatchlist(ticker),
    onSuccess: (_, ticker) => {
      queryClient.invalidateQueries({ queryKey: ["watchlist"] })
      toast("success", "Removed", `${ticker} removed from watchlist`)
    },
  })

  const priorityMutation = useMutation({
    mutationFn: ({ ticker, priority }: { ticker: string; priority: number }) =>
      api.updateWatchlistItem(ticker, { priority }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["watchlist"] }),
  })

  const handleAnalyze = async (ticker: string) => {
    setAnalyzingTicker(ticker)
    setAnalysisResult(null)
    try {
      const result = await api.analyzeTicker(ticker, 3)
      setAnalysisResult(result)
    } catch (e) {
      toast("error", "Analysis Failed", String(e))
    } finally {
      setAnalyzingTicker(null)
    }
  }

  const items = watchlist ?? []

  return (
    <>
      <PageHeader
        title="Watchlist"
        description="Track tickers of interest with scores, news, and earnings"
        actions={
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={addTicker}
              onChange={(e) => setAddTicker(e.target.value.toUpperCase())}
              onKeyDown={(e) => {
                if (e.key === "Enter" && addTicker.trim()) addMutation.mutate(addTicker.trim())
              }}
              placeholder="Add ticker..."
              className="w-36 rounded-lg border border-border/60 bg-[#0a0a0f] px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground/40 focus:border-primary/50 focus:outline-none"
            />
            <Button
              size="sm"
              onClick={() => addTicker.trim() && addMutation.mutate(addTicker.trim())}
              disabled={addMutation.isPending || !addTicker.trim()}
            >
              {addMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            </Button>
          </div>
        }
      />

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Star className="h-10 w-10 text-muted-foreground/30 mx-auto mb-3" />
            <p className="text-muted-foreground">No tickers on your watchlist yet.</p>
            <p className="text-xs text-muted-foreground/60 mt-1">Add tickers using the input above.</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <Card key={item.ticker} className="hover:border-border/80 transition-colors">
              <CardContent className="py-3">
                <div className="flex items-center gap-4">
                  {/* Priority star */}
                  <button
                    onClick={() =>
                      priorityMutation.mutate({
                        ticker: item.ticker,
                        priority: (item.priority ?? 1) >= 3 ? 1 : (item.priority ?? 1) + 1,
                      })
                    }
                    className="shrink-0"
                  >
                    <Star
                      className={cn(
                        "h-4 w-4 transition-colors",
                        (item.priority ?? 1) >= 3
                          ? "text-amber-400 fill-amber-400"
                          : (item.priority ?? 1) >= 2
                            ? "text-amber-400"
                            : "text-muted-foreground/40",
                      )}
                    />
                  </button>

                  {/* Ticker + name */}
                  <div className="w-28">
                    <p className="text-sm font-bold">{item.ticker}</p>
                    <p className="text-[10px] text-muted-foreground truncate">
                      {item.company_name || item.sub_sector || ""}
                    </p>
                  </div>

                  {/* Score */}
                  <div className="w-16 text-center">
                    {item.score_decile != null ? (
                      <div className="flex flex-col items-center">
                        <span className="text-xs text-muted-foreground">Decile</span>
                        <span
                          className={cn(
                            "text-sm font-bold",
                            item.score_decile >= 8 ? "text-profit" : item.score_decile <= 3 ? "text-loss" : "text-foreground",
                          )}
                        >
                          {item.score_decile}
                        </span>
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground/40">-</span>
                    )}
                  </div>

                  {/* Quality */}
                  <div className="w-16 text-center">
                    {item.quality_score != null ? (
                      <div className="flex flex-col items-center">
                        <span className="text-xs text-muted-foreground">Quality</span>
                        <span className="text-sm font-medium">{(item.quality_score * 100).toFixed(0)}%</span>
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground/40">-</span>
                    )}
                  </div>

                  {/* Sentiment */}
                  <div className="w-20 flex justify-center">{sentimentBadge(item.sentiment)}</div>

                  {/* Earnings countdown */}
                  <div className="w-16 flex justify-center">{earningsCountdown(item)}</div>

                  {/* Notes */}
                  <div className="flex-1 min-w-0">
                    {item.notes && (
                      <p className="text-xs text-muted-foreground truncate">{item.notes}</p>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 text-[11px] px-2"
                      onClick={() => handleAnalyze(item.ticker)}
                      disabled={analyzingTicker === item.ticker}
                    >
                      {analyzingTicker === item.ticker ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <>
                          <Search className="h-3 w-3 mr-1" />
                          Analyze
                        </>
                      )}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 px-1.5 border-red-500/30 text-red-400 hover:bg-red-500/10"
                      onClick={() => removeMutation.mutate(item.ticker)}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Analysis result */}
      {analysisResult && (
        <div className="mt-6">
          <Card>
            <CardTitle className="flex items-center justify-between">
              <span>Analysis: {analysisResult.ticker}</span>
              <Button variant="outline" size="sm" onClick={() => setAnalysisResult(null)} className="h-7 text-xs">
                Close
              </Button>
            </CardTitle>
            <CardContent className="space-y-4">
              <div className="flex items-center gap-4">
                <div
                  className={cn(
                    "rounded-lg border-2 px-4 py-2 font-bold text-lg",
                    analysisResult.recommendation === "BUY"
                      ? "text-profit border-profit/40 bg-profit/10"
                      : analysisResult.recommendation === "SELL"
                        ? "text-loss border-loss/40 bg-loss/10"
                        : "text-amber-400 border-amber-500/40 bg-amber-500/10",
                  )}
                >
                  {analysisResult.recommendation}
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Confidence</p>
                  <p className="text-xl font-bold">{((analysisResult.confidence ?? 0) * 100).toFixed(0)}%</p>
                </div>
              </div>

              {analysisResult.summary && (
                <p className="text-sm rounded-lg bg-muted/30 border border-border/40 p-3">{analysisResult.summary}</p>
              )}

              <div className="grid grid-cols-2 gap-3 text-xs">
                {analysisResult.fundamentals && (
                  <div>
                    <p className="font-semibold text-muted-foreground mb-1">Fundamentals</p>
                    <p>{analysisResult.fundamentals}</p>
                  </div>
                )}
                {analysisResult.technicals && (
                  <div>
                    <p className="font-semibold text-muted-foreground mb-1">Technicals</p>
                    <p>{analysisResult.technicals}</p>
                  </div>
                )}
              </div>

              {analysisResult.risk_factors && analysisResult.risk_factors.length > 0 && (
                <div className="text-xs">
                  <p className="font-semibold text-loss mb-1">Risk Factors</p>
                  <ul className="space-y-0.5">
                    {analysisResult.risk_factors.map((r, i) => (
                      <li key={i} className="text-muted-foreground">· {r}</li>
                    ))}
                  </ul>
                </div>
              )}

              {analysisResult.catalysts && analysisResult.catalysts.length > 0 && (
                <div className="text-xs">
                  <p className="font-semibold text-profit mb-1">Catalysts</p>
                  <ul className="space-y-0.5">
                    {analysisResult.catalysts.map((c, i) => (
                      <li key={i} className="text-muted-foreground">· {c}</li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </>
  )
}
