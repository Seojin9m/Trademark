import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { usePipeline } from "@/contexts/pipeline-context"
import { useToast } from "@/contexts/toast-context"
import type { PipelineEvent } from "@/contexts/pipeline-context"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { GateReviewPanel } from "@/components/pipeline/GateReviewPanel"
import {
  Play, Loader2, CheckCircle, XCircle, Clock, ArrowRight,
  Trash2, RotateCcw, StickyNote, X, Save, ImagePlus,
  Hand, Eye, ChevronDown, ChevronUp, Database, ExternalLink,
  Search, Zap, Target, TrendingUp,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { api, type SectorInfo, type TickerAnalysis, type PipelineRunParams } from "@/lib/api"

const stepOrder = ["ingestion", "fundamentals", "scoring", "adaptive", "signals", "proposals", "research", "judge", "execution", "pnl", "learning", "complete"]

const stepLabels: Record<string, string> = {
  ingestion: "Data Ingestion",
  fundamentals: "Fundamentals",
  scoring: "Factor Scoring",
  adaptive: "Adaptive Analysis",
  signals: "Signal Generation",
  proposals: "Trade Proposals",
  research: "News Research",
  judge: "LLM Judge",
  execution: "Auto Execution",
  pnl: "P&L Update",
  learning: "Self-Learning",
  complete: "Complete",
}

type StepState = "ok" | "run" | "err" | "gate" | "idle"

function stepStateFromEvent(ev: PipelineEvent | undefined): StepState {
  if (!ev) return "idle"
  if (ev.status === "running") return "run"
  if (ev.status === "done") return "ok"
  if (ev.status === "error") return "err"
  if (ev.status === "gate") return "gate"
  return "idle"
}

const STEP_COLOR: Record<StepState, string> = {
  ok: "text-profit",
  run: "text-primary",
  err: "text-loss",
  gate: "text-warn",
  idle: "text-muted-2",
}

const STEP_BORDER: Record<StepState, string> = {
  ok: "border-profit",
  run: "border-primary",
  err: "border-loss",
  gate: "border-warn",
  idle: "border-line",
}

function StepIndicator({ state }: { state: StepState }) {
  return (
    <div
      className={cn(
        "flex items-center justify-center h-[22px] w-[22px] rounded-full shrink-0 border-[1.5px]",
        state === "idle" ? "bg-bg-2" : "bg-surface",
        STEP_BORDER[state],
        STEP_COLOR[state],
      )}
    >
      {state === "ok" && <Check className="h-[11px] w-[11px]" />}
      {state === "run" && <Loader2 className="h-[11px] w-[11px] animate-spin" />}
      {state === "err" && <XIcon className="h-[11px] w-[11px]" />}
      {state === "gate" && <span className="h-[8px] w-[8px] rounded-full bg-warn animate-pulse" />}
      {state === "idle" && <span className="h-[6px] w-[6px] rounded-full bg-muted-2" />}
    </div>
  )
}

function StepTracker({ events, eventTimestamps }: { events: PipelineEvent[]; eventTimestamps: Map<number, number> }) {
  const latestByStep = new Map<string, PipelineEvent>()
  events.forEach((e) => latestByStep.set(e.step, e))

  const stepElapsed = new Map<string, number>()
  const stepStartTs = new Map<string, number>()
  events.forEach((e, i) => {
    const ts = eventTimestamps.get(i)
    if (!ts) return
    if (e.status === "running" && !stepStartTs.has(e.step)) stepStartTs.set(e.step, ts)
    if ((e.status === "done" || e.status === "error") && stepStartTs.has(e.step)) {
      stepElapsed.set(e.step, (ts - stepStartTs.get(e.step)!) / 1000)
    }
  })

  const formatElapsed = (secs: number) => {
    if (secs < 1) return "<1s"
    if (secs < 60) return `${Math.round(secs)}s`
    const m = Math.floor(secs / 60)
    const s = Math.round(secs % 60)
    return s > 0 ? `${m}m ${s}s` : `${m}m`
  }

  // Find the index of the currently-running step so the connector line above
  // it can be colored as completed.
  const lastDoneIdx = stepOrder.reduce((maxIdx, step, i) => {
    const ev = latestByStep.get(step)
    return ev?.status === "done" ? i : maxIdx
  }, -1)

  return (
    <div className="flex flex-col">
      {stepOrder.map((step, i) => {
        const ev = latestByStep.get(step)
        const state = stepStateFromEvent(ev)
        const elapsed = stepElapsed.get(step)
        const isLast = i === stepOrder.length - 1
        const lineDone = i <= lastDoneIdx
        return (
          <div key={step} className="flex items-start gap-2.5 relative py-2">
            <div className="relative">
              <StepIndicator state={state} />
              {!isLast && (
                <div
                  className={cn(
                    "absolute left-[10.5px] top-[22px] w-px",
                    lineDone ? "bg-profit" : "bg-line",
                  )}
                  style={{ height: 16 }}
                />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div
                className={cn(
                  "text-[12.5px]",
                  state === "idle" ? "text-muted-foreground font-medium" : "text-foreground font-semibold",
                  state === "gate" && "text-warn",
                  state === "run" && "text-primary",
                )}
              >
                {stepLabels[step] || step}
              </div>
              {state !== "idle" && (
                <div className="font-mono text-[10.5px] text-muted-2">
                  {state === "ok" && elapsed != null ? `completed in ${formatElapsed(elapsed)}` : null}
                  {state === "run" ? "running…" : null}
                  {state === "err" ? "error" : null}
                  {state === "gate" ? "awaiting review" : null}
                </div>
              )}
            </div>
            {state === "gate" && <Badge variant="warn">REVIEW</Badge>}
          </div>
        )
      })}
    </div>
  )
}

// ─── Inline data display for non-gate steps ───
function StepDataDisplay({ event }: { event: PipelineEvent }) {
  const [open, setOpen] = useState(false)
  const data = event.gate_data
  if (!data) return null

  return (
    <div className="rounded-[4px] border border-info/20 bg-info/[0.02] mt-1">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-2 px-3 py-1.5 text-left">
        <Eye className="h-3 w-3 text-info" />
        <span className="text-[11px] text-info font-medium">{event.step} data</span>
        <span className="flex-1" />
        {open ? <ChevronUp className="h-3 w-3 text-muted-foreground" /> : <ChevronDown className="h-3 w-3 text-muted-foreground" />}
      </button>
      {open && (
        <div className="px-3 pb-2">
          <pre className="text-[10px] text-muted-foreground max-h-[10rem] overflow-y-auto">
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

function ReviewModeToggle() {
  const queryClient = useQueryClient()
  const { toast } = useToast()

  const { data: reviewMode } = useQuery({
    queryKey: ["review-mode"],
    queryFn: api.getReviewMode,
    refetchInterval: 5000,
  })

  const mutation = useMutation({
    mutationFn: api.setReviewMode,
    onSuccess: (data) => {
      queryClient.setQueryData(["review-mode"], data)
      toast(
        data.enabled ? "info" : "success",
        data.enabled ? "Review Mode Enabled" : "Review Mode Disabled",
        data.enabled
          ? "Pipeline will pause at key stages for your review"
          : "Pipeline will run autonomously without pausing",
      )
    },
  })

  const enabled = reviewMode?.enabled ?? true

  return (
    <Card>
      <CardTitle meta="Pause at gates for human review">Review Mode</CardTitle>
      <CardContent>
        <div className="flex items-center gap-4">
          <button
            onClick={() => mutation.mutate(!enabled)}
            disabled={mutation.isPending}
            className={cn(
              "relative h-[24px] w-[44px] rounded-full border border-line-2 transition-colors disabled:opacity-50",
              enabled ? "bg-primary" : "bg-bg-2",
            )}
            aria-pressed={enabled}
          >
            <span
              className={cn(
                "absolute top-px h-[20px] w-[20px] rounded-full transition-all",
                enabled ? "left-[21px] bg-background" : "left-px bg-muted-foreground",
              )}
            />
          </button>
          <div className="flex-1 min-w-0">
            <div className="text-[13px] font-medium">{enabled ? "Enabled" : "Disabled"}</div>
            <div className="text-[11.5px] text-muted-foreground">
              {enabled
                ? "Pipeline pauses at gates for approval/override"
                : "Pipeline runs end-to-end without interruption"}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function UserNotesPanel() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [draft, setDraft] = useState("")
  const [images, setImages] = useState<{ name: string; dataUrl: string }[]>([])
  const [open, setOpen] = useState(true)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const { data: notes } = useQuery({
    queryKey: ["user-notes"],
    queryFn: api.getUserNotes,
  })

  const saveMutation = useMutation({
    mutationFn: (payload: { text: string; images: { name: string; data: string; mime: string }[] }) =>
      api.setUserNotes(payload.text, payload.images),
    onSuccess: (data) => {
      queryClient.setQueryData(["user-notes"], data)
      toast("success", "Notes Saved", "Your context will be included in the next pipeline run")
    },
  })

  const clearMutation = useMutation({
    mutationFn: api.clearUserNotes,
    onSuccess: (data) => {
      queryClient.setQueryData(["user-notes"], data)
      setDraft("")
      setImages([])
      toast("success", "Notes Cleared", "User context removed")
    },
  })

  const hasNotes = !!(notes?.text) || !!(notes?.images?.length)

  useEffect(() => {
    if (notes?.text !== undefined && draft === "" && notes.text) {
      setDraft(notes.text)
    }
    if (notes?.images?.length && images.length === 0) {
      setImages(notes.images.map((img: { name: string; data: string }) => ({
        name: img.name,
        dataUrl: `data:image/png;base64,${img.data}`,
      })))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notes?.text, notes?.images])

  const handleSave = () => {
    const imagePayloads = images.map((img) => {
      const match = img.dataUrl.match(/^data:(image\/\w+);base64,(.+)$/)
      return {
        name: img.name,
        data: match ? match[2] : img.dataUrl,
        mime: match ? match[1] : "image/png",
      }
    })
    saveMutation.mutate({ text: draft, images: imagePayloads })
  }

  const addImageFile = (file: File) => {
    if (!file.type.startsWith("image/")) return
    if (file.size > 5 * 1024 * 1024) {
      toast("error", "Image Too Large", "Max 5MB per image")
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      setImages((prev) => [...prev, { name: file.name, dataUrl: reader.result as string }])
    }
    reader.readAsDataURL(file)
  }

  const handleImageAdd = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files) return
    Array.from(files).forEach(addImageFile)
    e.target.value = ""
  }

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items
    if (!items) return
    for (const item of Array.from(items)) {
      if (item.type.startsWith("image/")) {
        e.preventDefault()
        const file = item.getAsFile()
        if (file) addImageFile(file)
      }
    }
  }

  const removeImage = (idx: number) => {
    setImages((prev) => prev.filter((_, i) => i !== idx))
  }

  return (
    <Card>
      <CardTitle
        meta="Inject context into next run"
        action={
          <button
            onClick={() => setOpen(!open)}
            className="flex items-center gap-1 h-[24px] px-2 rounded-[4px] font-mono text-[11px] font-medium text-muted-foreground hover:text-foreground hover:bg-surface-2 transition-colors"
          >
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
            {open ? "Hide" : "Show"}
          </button>
        }
      >
        User Notes
        {hasNotes && <Badge variant="accent">ACTIVE</Badge>}
      </CardTitle>
      {open && (
        <CardContent>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onPaste={handlePaste}
            placeholder={"Share context for the judge to consider...\n\nExamples:\n• \"NVDA earnings beat expectations\"\n• \"Tariff concerns in semiconductor sector\""}
            className="w-full h-28 rounded-[4px] bg-bg-2 border border-line px-3 py-2.5 font-mono text-[12px] text-foreground placeholder:text-muted-2 resize-none focus:outline-none focus:border-primary/50"
          />

          {images.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-2">
              {images.map((img, idx) => (
                <div key={idx} className="relative group">
                  <img
                    src={img.dataUrl}
                    alt={img.name}
                    className="h-16 w-16 object-cover rounded-[4px] border border-line"
                  />
                  <button
                    onClick={() => removeImage(idx)}
                    className="absolute -top-1.5 -right-1.5 h-5 w-5 rounded-full bg-loss text-background flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="flex items-center gap-1.5 mt-3">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={handleImageAdd}
            />
            <Button size="sm" variant="default" onClick={() => fileInputRef.current?.click()}>
              <ImagePlus className="h-3 w-3" />
              Attach
            </Button>
            {hasNotes && (
              <Button
                size="sm"
                variant="default"
                onClick={() => clearMutation.mutate()}
                disabled={clearMutation.isPending}
              >
                {clearMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <X className="h-3 w-3" />}
                Clear
              </Button>
            )}
            <span className="flex-1" />
            <Button
              size="sm"
              variant="primary"
              onClick={handleSave}
              disabled={saveMutation.isPending || (!draft.trim() && images.length === 0)}
            >
              {saveMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
              Save Notes
            </Button>
          </div>
        </CardContent>
      )}
    </Card>
  )
}

function StartOverButton() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [confirming, setConfirming] = useState(false)
  const [keepPrices, setKeepPrices] = useState(true)

  const mutation = useMutation({
    mutationFn: () => api.resetTradingData(keepPrices),
    onSuccess: (data) => {
      queryClient.invalidateQueries()
      toast("success", "Reset Complete", `Cleared ${data.cleared.length} data stores`)
      setConfirming(false)
    },
    onError: () => {
      toast("error", "Reset Failed", "Check backend logs for details")
    },
  })

  return (
    <>
      <Button
        size="sm"
        variant="destructive"
        onClick={() => setConfirming(true)}
      >
        <RotateCcw className="h-3 w-3" />
        Start Over
      </Button>

      {confirming && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-md border border-loss/40 bg-surface p-5">
            <div className="flex items-center gap-3 mb-4">
              <div className="flex items-center justify-center h-10 w-10 rounded-full bg-loss/15">
                <Trash2 className="h-5 w-5 text-loss" />
              </div>
              <div>
                <h3 className="text-[15px] font-semibold">Start Over?</h3>
                <p className="text-[12px] text-muted-foreground">This will delete all trading data</p>
              </div>
            </div>

            <div className="rounded-[4px] bg-loss/10 border border-loss/20 p-3 mb-4">
              <p className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.08em] text-loss mb-2">
                Permanently deleted:
              </p>
              <ul className="text-[12px] text-loss/80 space-y-1 list-disc list-inside">
                <li>All trade proposals and execution history</li>
                <li>All decision outcomes and learning patterns</li>
                <li>All judge evaluation logs</li>
                <li>All news research data</li>
                <li>Adaptive strategy state</li>
                <li>Portfolio re-synced from Wealthsimple (or reset to $100k if disconnected)</li>
              </ul>
            </div>

            <label className="flex items-center gap-2 mb-5 cursor-pointer">
              <input
                type="checkbox"
                checked={keepPrices}
                onChange={(e) => setKeepPrices(e.target.checked)}
                className="accent-primary h-4 w-4"
              />
              <span className="text-[12.5px] text-muted-foreground">Keep price &amp; fundamental data (recommended)</span>
            </label>

            <div className="flex gap-2">
              <Button variant="default" className="flex-1" onClick={() => setConfirming(false)}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                className="flex-1"
                onClick={() => mutation.mutate()}
                disabled={mutation.isPending}
              >
                {mutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
                Delete &amp; Reset
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

const RISK_LABELS = ["", "Conservative", "Cautious", "Balanced", "Growth", "Aggressive"]
const RISK_COLORS = ["", "text-blue-400", "text-sky-400", "text-emerald-400", "text-amber-400", "text-red-400"]

function PipelineSettings({
  mode,
  setMode,
  riskLevel,
  setRiskLevel,
  selectedSector,
  setSelectedSector,
  tickerInput,
  setTickerInput,
  onAnalyzeTicker,
  analyzing,
}: {
  mode: "full" | "sector" | "ticker"
  setMode: (m: "full" | "sector" | "ticker") => void
  riskLevel: number
  setRiskLevel: (n: number) => void
  selectedSector: string
  setSelectedSector: (s: string) => void
  tickerInput: string
  setTickerInput: (s: string) => void
  onAnalyzeTicker: () => void
  analyzing: boolean
}) {
  const { data: sectors } = useQuery({
    queryKey: ["sectors"],
    queryFn: api.getSectors,
    staleTime: 60_000,
  })

  return (
    <div className="rounded-xl border-2 border-border/60 bg-card p-4 space-y-4">
      <div className="flex items-center gap-2 mb-1">
        <Target className="h-4 w-4 text-primary" />
        <p className="text-sm font-semibold">Pipeline Mode</p>
      </div>

      {/* Mode selector */}
      <div className="flex gap-2">
        {(["full", "sector", "ticker"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={cn(
              "flex-1 rounded-lg border px-3 py-2 text-xs font-medium transition-colors",
              mode === m
                ? "border-primary/50 bg-primary/10 text-primary"
                : "border-border/60 bg-muted/40 text-muted-foreground hover:bg-muted/60",
            )}
          >
            {m === "full" && "Full Pipeline"}
            {m === "sector" && "Sector Filter"}
            {m === "ticker" && "Single Ticker"}
          </button>
        ))}
      </div>

      {/* Sector dropdown */}
      {mode === "sector" && (
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Sub-sector</label>
          <select
            value={selectedSector}
            onChange={(e) => setSelectedSector(e.target.value)}
            className="w-full rounded-lg border border-border/60 bg-[#0a0a0f] px-3 py-2 text-sm text-foreground focus:border-primary/50 focus:outline-none"
          >
            <option value="">Select a sector...</option>
            {sectors?.map((s: SectorInfo) => (
              <option key={s.sub_sector} value={s.sub_sector}>
                {s.sub_sector} ({s.ticker_count} tickers)
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Ticker input */}
      {mode === "ticker" && (
        <div className="flex gap-2">
          <div className="flex-1">
            <label className="text-xs text-muted-foreground mb-1 block">Ticker symbol</label>
            <input
              type="text"
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
              placeholder="e.g. AAPL"
              className="w-full rounded-lg border border-border/60 bg-[#0a0a0f] px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/40 focus:border-primary/50 focus:outline-none"
            />
          </div>
          <div className="flex items-end">
            <Button
              size="sm"
              onClick={onAnalyzeTicker}
              disabled={analyzing || !tickerInput.trim()}
              className="h-[38px]"
            >
              {analyzing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <>
                  <Search className="h-3.5 w-3.5 mr-1.5" />
                  Analyze
                </>
              )}
            </Button>
          </div>
        </div>
      )}

      {/* Risk level */}
      {mode !== "ticker" && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs text-muted-foreground">Risk Level</label>
            <span className={cn("text-xs font-medium", RISK_COLORS[riskLevel])}>
              {RISK_LABELS[riskLevel]} ({riskLevel})
            </span>
          </div>
          <input
            type="range"
            min={1}
            max={5}
            value={riskLevel}
            onChange={(e) => setRiskLevel(Number(e.target.value))}
            className="w-full h-2 rounded-full appearance-none bg-muted cursor-pointer accent-primary"
          />
          <div className="flex justify-between text-[10px] text-muted-foreground/60 mt-1">
            <span>Conservative</span>
            <span>Aggressive</span>
          </div>
        </div>
      )}

      {/* Risk level for ticker mode too */}
      {mode === "ticker" && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs text-muted-foreground">Risk Level</label>
            <span className={cn("text-xs font-medium", RISK_COLORS[riskLevel])}>
              {RISK_LABELS[riskLevel]} ({riskLevel})
            </span>
          </div>
          <input
            type="range"
            min={1}
            max={5}
            value={riskLevel}
            onChange={(e) => setRiskLevel(Number(e.target.value))}
            className="w-full h-2 rounded-full appearance-none bg-muted cursor-pointer accent-primary"
          />
          <div className="flex justify-between text-[10px] text-muted-foreground/60 mt-1">
            <span>Conservative</span>
            <span>Aggressive</span>
          </div>
        </div>
      )}
    </div>
  )
}

function TickerAnalysisCard({ analysis }: { analysis: TickerAnalysis }) {
  const recColor = analysis.recommendation === "BUY"
    ? "text-profit border-profit/40 bg-profit/10"
    : analysis.recommendation === "SELL"
      ? "text-loss border-loss/40 bg-loss/10"
      : "text-amber-400 border-amber-500/40 bg-amber-500/10"

  return (
    <Card>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={cn("rounded-lg border-2 px-4 py-2 font-bold text-lg", recColor)}>
              {analysis.recommendation}
            </div>
            <div>
              <p className="text-lg font-bold">{analysis.ticker}</p>
              <p className="text-xs text-muted-foreground">
                {analysis.metadata?.name || ""} · {analysis.metadata?.sub_sector || ""}
              </p>
            </div>
          </div>
          <div className="text-right">
            <p className="text-sm text-muted-foreground">Confidence</p>
            <p className="text-2xl font-bold tabular-nums">{((analysis.confidence ?? 0) * 100).toFixed(0)}%</p>
          </div>
        </div>

        {analysis.summary && (
          <div className="rounded-lg bg-muted/30 border border-border/40 p-3">
            <p className="text-sm">{analysis.summary}</p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          {analysis.fundamentals && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">Fundamentals</p>
              <p className="text-xs">{analysis.fundamentals}</p>
            </div>
          )}
          {analysis.technicals && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">Technicals</p>
              <p className="text-xs">{analysis.technicals}</p>
            </div>
          )}
          {analysis.competitive_position && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">Competitive Position</p>
              <p className="text-xs">{analysis.competitive_position}</p>
            </div>
          )}
          {analysis.sector_context && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">Sector Context</p>
              <p className="text-xs">{analysis.sector_context}</p>
            </div>
          )}
          {analysis.earnings_insight && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">Earnings</p>
              <p className="text-xs">{analysis.earnings_insight}</p>
            </div>
          )}
          {analysis.risk_level_note && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">Risk Note</p>
              <p className="text-xs">{analysis.risk_level_note}</p>
            </div>
          )}
        </div>

        {analysis.risk_factors && analysis.risk_factors.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-loss mb-1">Risk Factors</p>
            <ul className="text-xs space-y-0.5">
              {analysis.risk_factors.map((r, i) => (
                <li key={i} className="text-muted-foreground">· {r}</li>
              ))}
            </ul>
          </div>
        )}

        {analysis.catalysts && analysis.catalysts.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-profit mb-1">Catalysts</p>
            <ul className="text-xs space-y-0.5">
              {analysis.catalysts.map((c, i) => (
                <li key={i} className="text-muted-foreground">· {c}</li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function formatLogTime(ts: number): string {
  const d = new Date(ts)
  const hh = String(d.getHours()).padStart(2, "0")
  const mm = String(d.getMinutes()).padStart(2, "0")
  const ss = String(d.getSeconds()).padStart(2, "0")
  return `${hh}:${mm}:${ss}`
}

function logCheck(status: string): { char: string; cls: string } {
  if (status === "done") return { char: "✓", cls: "text-profit" }
  if (status === "running") return { char: "▶", cls: "text-primary" }
  if (status === "error") return { char: "✗", cls: "text-loss" }
  if (status === "gate") return { char: "⏸", cls: "text-warn" }
  if (status === "data") return { char: "◆", cls: "text-info" }
  return { char: "·", cls: "text-muted-2" }
}

export default function PipelineControl() {
  const { running, events, error, activeGate, lastCompletedRunId: _lastCompletedRunId, startPipeline, respondToGate } = usePipeline()
  const { toast } = useToast()
  const navigate = useNavigate()
  const logRef = useRef<HTMLDivElement>(null)
  const prevEventsLen = useRef(0)
  const eventTimestamps = useRef<Map<number, number>>(new Map())

  const [pipelineMode, setPipelineMode] = useState<"full" | "sector" | "ticker">("full")
  const [riskLevel, setRiskLevel] = useState(3)
  const [selectedSector, setSelectedSector] = useState("")
  const [tickerInput, setTickerInput] = useState("")
  const [tickerAnalysis, setTickerAnalysis] = useState<TickerAnalysis | null>(null)
  const [analyzing, setAnalyzing] = useState(false)

  useEffect(() => {
    if (events.length === 0) {
      eventTimestamps.current = new Map()
    } else {
      for (let i = 0; i < events.length; i++) {
        if (!eventTimestamps.current.has(i)) {
          eventTimestamps.current.set(i, Date.now())
        }
      }
    }
  }, [events])

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [events])

  // Toast on pipeline completion or error
  useEffect(() => {
    if (events.length <= prevEventsLen.current) {
      prevEventsLen.current = events.length
      return
    }
    prevEventsLen.current = events.length
    const latest = events[events.length - 1]
    if (latest.step === "complete" && latest.status === "done") {
      toast("success", "Pipeline Complete", latest.message)
    } else if (latest.status === "error") {
      toast("error", `Pipeline Error: ${latest.step}`, latest.message)
    }
  }, [events, toast])

  // Toast on connection error
  useEffect(() => {
    if (error) toast("error", "Pipeline Connection Lost", error)
  }, [error, toast])

  const isComplete = events.some((e) => e.step === "complete")
  const hasError = events.some((e) => e.status === "error")
  const completedSteps = new Set(events.filter((e) => e.status === "done").map((e) => e.step)).size
  const totalSteps = stepOrder.length - 1
  const progressPct = totalSteps > 0 ? (completedSteps / totalSteps) * 100 : 0

  const statusLabel = running ? "RUNNING" : hasError ? "ERROR" : isComplete ? "COMPLETE" : "IDLE"
  const statusVariant: "accent" | "loss" | "profit" | "muted" = running ? "accent" : hasError ? "loss" : isComplete ? "profit" : "muted"

  return (
    <>
      <PageHeader
        title="Pipeline Control"
        description="Manually trigger the EOD pipeline and watch progress in real-time"
        prefix={<Badge variant={statusVariant}>{statusLabel}</Badge>}
        actions={
          <div className="flex items-center gap-2">
            <StartOverButton />
            {pipelineMode !== "ticker" && (
              <Button
                variant="outline"
                onClick={() => {
                  const params: PipelineRunParams = { risk_level: riskLevel }
                  if (pipelineMode === "sector" && selectedSector) {
                    params.mode = "sector"
                    params.sub_sector = selectedSector
                  }
                  startPipeline(params)
                }}
                disabled={running || (pipelineMode === "sector" && !selectedSector)}
                className="border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10 hover:border-emerald-500/50"
              >
                {running ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Running...
                  </>
                ) : (
                  <>
                    <Play className="mr-2 h-4 w-4" />
                    {pipelineMode === "sector" ? "Run Sector Pipeline" : "Run Pipeline"}
                  </>
                )}
              </Button>
            )}
          </div>
        }
      />

      {/* Progress */}
      <Card className="mb-[14px]">
        <div className="flex items-center gap-3.5 px-[18px] py-3">
          <span className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
            Progress
          </span>
          <span className="font-mono text-[13px] font-semibold tabular-nums text-foreground">
            {completedSteps} / {totalSteps}
          </span>
          <div className="relative flex-1 h-1.5 rounded-[3px] bg-line overflow-hidden">
            <div
              className={cn(
                "absolute inset-y-0 left-0 rounded-[3px] transition-all duration-500 ease-out",
                hasError ? "bg-loss" : running ? "bg-primary" : isComplete ? "bg-profit" : "bg-muted-2",
              )}
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <span className="font-mono text-[11px] text-muted-2 tabular-nums min-w-[40px] text-right">
            {progressPct.toFixed(0)}%
          </span>
        </div>
      </Card>

      {/* Pipeline complete banner */}
      {isComplete && !hasError && !running && (
        <div className="mb-[14px] rounded-md border border-profit/40 bg-profit/[0.06] p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center h-9 w-9 rounded-[4px] bg-profit/15">
                <Check className="h-5 w-5 text-profit" />
              </div>
              <div>
                <p className="text-[13px] font-semibold">Pipeline Complete</p>
                <p className="text-[11.5px] text-muted-foreground mt-0.5">
                  {events.find((e) => e.step === "complete")?.message || "All steps finished successfully"}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="default" onClick={() => navigate("/")}>
                Portfolio
                <ExternalLink className="h-3 w-3" />
              </Button>
              <Button size="sm" variant="primary" onClick={() => navigate("/trades")}>
                View Trades
                <ArrowRight className="h-3 w-3" />
              </Button>
            </div>
          </div>
        </div>
      )}

      <div className="mb-4">
        <div className="grid grid-cols-3 gap-3">
          <PipelineSettings
            mode={pipelineMode}
            setMode={setPipelineMode}
            riskLevel={riskLevel}
            setRiskLevel={setRiskLevel}
            selectedSector={selectedSector}
            setSelectedSector={setSelectedSector}
            tickerInput={tickerInput}
            setTickerInput={setTickerInput}
            onAnalyzeTicker={async () => {
              if (!tickerInput.trim() || analyzing) return
              setAnalyzing(true)
              setTickerAnalysis(null)
              try {
                const result = await api.analyzeTicker(tickerInput.trim(), riskLevel)
                setTickerAnalysis(result)
                toast("success", "Analysis Complete", `${result.recommendation} recommendation for ${tickerInput}`)
              } catch (e) {
                toast("error", "Analysis Failed", String(e))
              } finally {
                setAnalyzing(false)
              }
            }}
            analyzing={analyzing}
          />
          <UserNotesPanel />
          <ReviewModeToggle />
        </div>
      </div>

      {/* Ticker analysis result */}
      {tickerAnalysis && pipelineMode === "ticker" && (
        <div className="mb-4">
          <TickerAnalysisCard analysis={tickerAnalysis} />
        </div>
      )}

      {/* Active Gate Review Panel */}
      {activeGate && (
        <div className="mb-[14px]">
          <GateReviewPanel
            gate={activeGate}
            onContinue={(overrides) => respondToGate("continue", overrides)}
            onAbort={() => respondToGate("abort")}
          />
        </div>
      )}

      {/* Steps + Live Log */}
      <div className="grid gap-[14px] items-start" style={{ gridTemplateColumns: "1fr 2fr" }}>
        <Card>
          <CardTitle meta={`${stepOrder.length} stages`}>Steps</CardTitle>
          <CardContent>
            <StepTracker events={events} eventTimestamps={eventTimestamps.current} />
          </CardContent>
        </Card>

        <Card>
          <CardTitle meta={`${events.length} entr${events.length === 1 ? "y" : "ies"} · auto-scroll`}>
            Live Log
          </CardTitle>
          <CardContent>
            <div
              ref={logRef}
              className="rounded-[4px] border border-line bg-[#050706] p-3.5 font-mono text-[11.5px] text-fg-dim overflow-y-auto"
              style={{ minHeight: 460, maxHeight: 460 }}
            >
              {events.length === 0 ? (
                <p className="text-muted-2">Click "Run Pipeline" to start…</p>
              ) : (
                events.map((e, i) => {
                  const ts = eventTimestamps.current.get(i)
                  const { char, cls } = logCheck(e.status)
                  const isLast = i === events.length - 1
                  return (
                    <div key={i}>
                      <div className="flex items-start gap-2.5 py-0.5">
                        <span className="text-muted-2 w-7 text-right shrink-0">
                          {String(i + 1).padStart(3, "0")}
                        </span>
                        <span className={cn("w-[14px] shrink-0", cls)}>{char}</span>
                        {ts && (
                          <span className="text-muted-2 shrink-0" style={{ minWidth: 52 }}>
                            {formatLogTime(ts)}
                          </span>
                        )}
                        <span className="text-primary font-semibold shrink-0">
                          [{e.step}]
                        </span>
                        <span
                          className={cn(
                            "flex-1 break-words",
                            e.status === "error" && "text-loss",
                            e.status === "running" && "text-foreground",
                            e.status === "done" && "text-fg-dim",
                            e.status === "gate" && "text-warn",
                            e.status === "data" && "text-info",
                          )}
                        >
                          {e.message}
                          {isLast && running && (
                            <span className="inline-block w-[7px] h-[12px] bg-primary align-[-2px] ml-1 animate-blink" />
                          )}
                        </span>
                      </div>
                      {e.status === "data" && e.gate_data && <StepDataDisplay event={e} />}
                    </div>
                  )
                })
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  )
}
