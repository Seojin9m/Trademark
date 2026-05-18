import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { RefreshCw } from "lucide-react"
import { api } from "@/lib/api"
import type {
  RankingsOverallRow,
  RankingsSectorsResponse,
  RankingsMarketSummaryResponse,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Sparkline } from "@/components/charts/Sparkline"

type FactorTab = "composite" | "momentum" | "quality"
type Period = "monthly" | "daily"

const TAB_LABEL: Record<FactorTab, string> = {
  composite: "Composite",
  momentum: "Momentum",
  quality: "Quality",
}

function fmtScore(v: number | null | undefined): string {
  if (v == null) return "—"
  return v.toFixed(2)
}

function fmtChange(v: number | null | undefined): string {
  if (v == null) return "—"
  return `${v >= 0 ? "▲" : "▼"} ${Math.abs(v).toFixed(2)}%`
}

// Decile 10 is the top decile in this codebase (compute_composite_scores uses
// pd.qcut bottom-up), so high deciles get the accent / profit treatment.
function decileVariant(d: number | null | undefined): "accent" | "profit" | "muted" {
  if (d == null) return "muted"
  if (d >= 9) return "accent"
  if (d >= 7) return "profit"
  return "muted"
}

export default function Rankings() {
  const [tab, setTab] = useState<FactorTab>("composite")
  const [period, setPeriod] = useState<Period>("monthly")
  const queryClient = useQueryClient()

  const { data: overall, isLoading: overallLoading } = useQuery<RankingsOverallRow[]>({
    queryKey: ["rankings-overall", tab],
    queryFn: () => api.getRankingsOverall(8, tab),
    staleTime: 60_000,
  })

  const { data: sectors, isLoading: sectorsLoading } = useQuery<RankingsSectorsResponse>({
    queryKey: ["rankings-sectors", period],
    queryFn: () => api.getRankingsSectors(period, 4),
    staleTime: 60_000,
  })

  const { data: market } = useQuery<RankingsMarketSummaryResponse>({
    queryKey: ["rankings-market-summary"],
    queryFn: api.getRankingsMarketSummary,
    staleTime: 60_000,
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["rankings-overall"] })
    queryClient.invalidateQueries({ queryKey: ["rankings-sectors"] })
    queryClient.invalidateQueries({ queryKey: ["rankings-market-summary"] })
  }

  const summary = market?.summary
  const spxSpark = market?.spx_spark ?? []

  const buySectors = (sectors?.sectors ?? []).filter((s) => s.action === "BUY")
  const sellSectors = (sectors?.sectors ?? []).filter((s) => s.action === "SELL")

  const overallMax = (overall?.length ?? 0) > 0 ? overall![0].composite : 10
  const universeCount = (sectors?.sectors ?? []).reduce(
    (sum, s) => sum + (s.total_names ?? 0),
    0,
  )
  const d10Count = (overall ?? []).filter((r) => r.decile === 10).length
  const spread =
    overall && overall.length > 1
      ? overall[0].composite - overall[overall.length - 1].composite
      : 0

  const dateText = sectors?.date ?? summary?.date ?? "—"
  const stanceClass =
    summary?.stance === "CONSTRUCTIVE"
      ? "text-primary"
      : summary?.stance === "DEFENSIVE"
        ? "text-loss"
        : "text-fg-dim"

  const actions = (
    <>
      <div className="flex overflow-hidden rounded-[4px] border border-line-2">
        {(Object.keys(TAB_LABEL) as FactorTab[]).map((t, i) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "h-[28px] px-3 font-mono text-[12px] font-medium transition-colors",
              i > 0 && "border-l border-line-2",
              tab === t
                ? "bg-primary/8 text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {TAB_LABEL[t]}
          </button>
        ))}
      </div>
      <button
        onClick={refresh}
        className="flex h-[28px] items-center gap-1.5 rounded-[4px] border border-line-2 px-3 font-mono text-[12px] text-muted-foreground transition-colors hover:text-foreground"
      >
        <RefreshCw className="h-3 w-3" />
        Refresh
      </button>
    </>
  )

  return (
    <>
      <PageHeader
        title="Rankings"
        description={`Ranked universe and sector signals · ${dateText}`}
        actions={actions}
      />

      {/* ────────── TOP ROW: Overall (left) + Market Summary (right) ────────── */}
      <div className="grid gap-4 mb-4" style={{ gridTemplateColumns: "1.6fr 1fr" }}>
        {/* OVERALL */}
        <Card>
          <div className="flex items-start justify-between border-b border-line px-4 py-3">
            <div>
              <div className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                ◆ OVERALL RANKINGS
              </div>
              <div className="mt-1 text-[15px] font-semibold tracking-[-0.01em]">
                Top 8 across the universe
              </div>
            </div>
            <div className="flex gap-5 font-mono">
              <Stat label="UNIV" value={universeCount > 0 ? String(universeCount) : "—"} />
              <Stat label="D10" value={String(d10Count)} accent />
              <Stat label="SPREAD" value={spread.toFixed(1)} />
            </div>
          </div>
          <CardContent>
            {overallLoading ? (
              <div className="space-y-1.5">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="h-10 animate-shimmer rounded-[4px]" />
                ))}
              </div>
            ) : !overall || overall.length === 0 ? (
              <EmptyHint
                title="No rankings yet"
                hint="Run the EOD pipeline to populate factor_scores."
              />
            ) : (
              <div className="space-y-1">
                {overall.map((row, i) => {
                  const isPodium = i < 3
                  const widthPct = Math.max(
                    8,
                    overallMax > 0 ? (row.composite / overallMax) * 100 : 0,
                  )
                  return (
                    <div
                      key={row.ticker}
                      className={cn(
                        "grid items-center gap-3 rounded-[4px] px-2 py-2 transition-colors hover:bg-surface-2",
                        isPodium && "bg-primary/[0.03]",
                      )}
                      style={{
                        gridTemplateColumns:
                          "32px minmax(0,1.1fr) minmax(0,1fr) minmax(0,1.4fr) 48px 80px",
                      }}
                    >
                      <span
                        className={cn(
                          "font-mono text-[13px] font-semibold tabular-nums",
                          isPodium ? "text-primary" : "text-muted-2",
                        )}
                      >
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <div className="min-w-0">
                        <div className="text-[13px] font-semibold text-foreground">
                          {row.ticker}
                        </div>
                        <div className="truncate font-mono text-[10.5px] text-muted-foreground">
                          {row.name ?? "—"}
                        </div>
                      </div>
                      <div className="font-mono text-[11px] uppercase tracking-[0.04em] text-fg-dim">
                        {row.sector ?? "—"}
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="w-12 font-mono text-[13px] font-medium tabular-nums">
                          {fmtScore(row.composite)}
                        </span>
                        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line-2">
                          <div
                            className="h-full rounded-full bg-primary"
                            style={{ width: `${widthPct}%` }}
                          />
                        </div>
                      </div>
                      <Badge variant={decileVariant(row.decile)}>D{row.decile}</Badge>
                      <div
                        className={cn(
                          "text-right font-mono text-[11.5px] font-medium tabular-nums",
                          row.change_pct >= 0 ? "text-profit" : "text-loss",
                        )}
                      >
                        {fmtChange(row.change_pct)}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>

        {/* MARKET SUMMARY */}
        <Card>
          <div className="flex items-start justify-between border-b border-line px-4 py-3">
            <div>
              <div className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                ◆ MARKET STANCE
              </div>
              <div className={cn("mt-1 text-[15px] font-semibold tracking-[-0.01em]", stanceClass)}>
                {summary?.stance ?? "—"}
              </div>
            </div>
            <div className="flex flex-col items-end gap-1">
              <span className="font-mono text-[9.5px] tracking-[0.08em] text-muted-2">
                SPX 30D
              </span>
              {spxSpark.length > 1 ? (
                <Sparkline data={spxSpark} width={140} height={32} />
              ) : (
                <div className="h-8 w-[140px]" />
              )}
              <div className="font-mono text-[11px] tabular-nums">
                <span>
                  {summary?.spx_close != null ? summary.spx_close.toFixed(2) : "—"}
                </span>
                {summary?.spx_change != null && (
                  <span
                    className={cn(
                      "ml-1.5",
                      summary.spx_change >= 0 ? "text-profit" : "text-loss",
                    )}
                  >
                    {summary.spx_change >= 0 ? "+" : ""}
                    {(summary.spx_change * 100).toFixed(2)}%
                  </span>
                )}
              </div>
            </div>
          </div>
          <CardContent>
            <p className="text-[12.5px] leading-relaxed text-fg-dim">
              {summary?.narrative ||
                "EOD pipeline has not yet generated a market narrative. Run the pipeline (or wait until tonight) to populate this card."}
            </p>

            <div className="mt-4 grid grid-cols-3 gap-2.5">
              <KPIBox value={summary?.buy_sectors ?? 0} label="BUY" tone="profit" />
              <KPIBox value={summary?.sell_sectors ?? 0} label="SELL" tone="loss" />
              <KPIBox
                value={summary?.vix != null ? summary.vix.toFixed(1) : "—"}
                label="VIX"
                tone="neutral"
              />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ────────── SECTION HEADER ────────── */}
      <div className="mb-3 flex items-center gap-3">
        <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground">
          Sector Rankings
        </span>
        <span className="h-px flex-1 bg-line" />
        <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-2">
          SIGNAL BASIS
        </span>
        <div className="flex overflow-hidden rounded-[4px] border border-line-2">
          {(["monthly", "daily"] as Period[]).map((p, i) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={cn(
                "h-[24px] px-2.5 font-mono text-[11px] font-medium transition-colors",
                i > 0 && "border-l border-line-2",
                period === p
                  ? "bg-primary/8 text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {p === "monthly" ? "Monthly" : "Daily"}
            </button>
          ))}
        </div>
        <span className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-[0.1em] text-muted-2">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-profit" /> BUY
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-loss" /> SELL
          </span>
        </span>
      </div>

      {sectorsLoading ? (
        <div className="grid grid-cols-2 gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-48 animate-shimmer rounded-md" />
          ))}
        </div>
      ) : (
        <div className="space-y-6">
          <SectorSide
            title="Constructive sectors"
            pill="LONG · BUY"
            pillTone="profit"
            sectors={buySectors}
          />
          <SectorSide
            title="Defensive / fade sectors"
            pill="SHORT · SELL"
            pillTone="loss"
            sectors={sellSectors}
          />
        </div>
      )}
    </>
  )
}

/* ──────────────────────── helper components ──────────────────────── */

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="flex flex-col items-end gap-0.5">
      <span className="font-mono text-[9.5px] uppercase tracking-[0.12em] text-muted-2">
        {label}
      </span>
      <span
        className={cn(
          "font-mono text-[15px] font-semibold tabular-nums",
          accent ? "text-primary" : "text-foreground",
        )}
      >
        {value}
      </span>
    </div>
  )
}

function KPIBox({
  value,
  label,
  tone,
}: {
  value: number | string
  label: string
  tone: "profit" | "loss" | "neutral"
}) {
  const toneClass =
    tone === "profit"
      ? "border-profit/40 bg-profit/8 text-profit"
      : tone === "loss"
        ? "border-loss/40 bg-loss/8 text-loss"
        : "border-line-2 bg-bg-2 text-fg-dim"
  return (
    <div className={cn("flex flex-col items-center gap-0.5 rounded-md border px-2 py-2.5", toneClass)}>
      <span className="font-mono text-[18px] font-semibold tabular-nums">{value}</span>
      <span className="font-mono text-[9.5px] uppercase tracking-[0.12em] opacity-80">
        {label}
      </span>
    </div>
  )
}

function EmptyHint({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 py-12 text-center">
      <div className="text-[13px] font-semibold">{title}</div>
      <div className="font-mono text-[11px] text-muted-foreground">{hint}</div>
    </div>
  )
}

function SectorSide({
  title,
  pill,
  pillTone,
  sectors,
}: {
  title: string
  pill: string
  pillTone: "profit" | "loss"
  sectors: RankingsSectorsResponse["sectors"]
}) {
  const pillClass =
    pillTone === "profit"
      ? "border-profit/50 bg-profit/12 text-profit"
      : "border-loss/50 bg-loss/12 text-loss"
  return (
    <section>
      <div className="mb-2 flex items-center gap-3">
        <span
          className={cn(
            "rounded-[3px] border px-2 py-[3px] font-mono text-[10px] font-semibold uppercase tracking-[0.08em]",
            pillClass,
          )}
        >
          {pill}
        </span>
        <span className="text-[12.5px] font-semibold text-foreground">{title}</span>
        <span className="h-px flex-1 bg-line" />
        <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-2">
          {sectors.length} {sectors.length === 1 ? "SECTOR" : "SECTORS"}
        </span>
      </div>

      {sectors.length === 0 ? (
        <div className="rounded-md border border-line bg-surface px-4 py-6 text-center font-mono text-[11px] text-muted-foreground">
          No sectors on this side.
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-3">
          {sectors.map((sec) => (
            <SectorCard key={sec.sector} sec={sec} />
          ))}
        </div>
      )}
    </section>
  )
}

function SectorCard({ sec }: { sec: RankingsSectorsResponse["sectors"][number] }) {
  const isBuy = sec.action === "BUY"
  const accentBar = isBuy ? "bg-profit" : "bg-loss"
  const maxScore = sec.top.length > 0 ? sec.top[0].composite ?? 1 : 1
  return (
    <Card className="relative overflow-hidden">
      <span className={cn("absolute inset-y-0 left-0 w-[3px]", accentBar)} />
      <div className="border-b border-line px-3 py-2.5 pl-4">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate text-[13px] font-semibold text-foreground">
              {sec.sector}
            </div>
            <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted-2">
              {sec.total_names} NAMES · {sec.breadth_top} TOP-3
            </div>
          </div>
          <div className="flex flex-col items-end gap-0.5">
            <span
              className={cn(
                "rounded-[3px] px-1.5 py-[2px] font-mono text-[10px] font-bold uppercase tracking-[0.08em]",
                isBuy ? "bg-profit/15 text-profit" : "bg-loss/15 text-loss",
              )}
            >
              {sec.action}
            </span>
            <span
              className={cn(
                "font-mono text-[11px] font-semibold tabular-nums",
                isBuy ? "text-profit" : "text-loss",
              )}
            >
              α {sec.alpha_pct >= 0 ? "+" : ""}
              {sec.alpha_pct.toFixed(2)}%
            </span>
          </div>
        </div>
      </div>
      <div className="pl-4">
        {sec.top.length === 0 ? (
          <div className="px-3 py-4 text-center font-mono text-[10.5px] text-muted-2">
            No D1-D3 candidates
          </div>
        ) : (
          <div className="divide-y divide-line/60">
            {sec.top.map((r, i) => {
              const widthPct =
                r.composite != null && maxScore > 0
                  ? Math.max(10, (r.composite / maxScore) * 100)
                  : 10
              return (
                <div
                  key={r.ticker}
                  className="grid items-center gap-2 px-3 py-1.5"
                  style={{
                    gridTemplateColumns: "18px minmax(0,1fr) minmax(0,1fr) 44px",
                  }}
                >
                  <span className="font-mono text-[11px] text-muted-2">{i + 1}</span>
                  <div className="min-w-0">
                    <div className="text-[12px] font-semibold text-foreground">
                      {r.ticker}
                    </div>
                    <div className="truncate font-mono text-[9.5px] text-muted-foreground">
                      {r.name ?? "—"}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-8 font-mono text-[11px] tabular-nums">
                      {fmtScore(r.composite)}
                    </span>
                    <div className="h-1 flex-1 overflow-hidden rounded-full bg-line-2">
                      <div
                        className={cn("h-full rounded-full", accentBar)}
                        style={{ width: `${widthPct}%` }}
                      />
                    </div>
                  </div>
                  <div className="text-right">
                    <Badge variant={decileVariant(r.decile)}>D{r.decile}</Badge>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </Card>
  )
}
