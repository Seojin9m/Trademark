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
} from "lucide-react"
import { cn } from "@/lib/utils"
import { api } from "@/lib/api"

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

function stepIcon(status: string, size = "h-4 w-4") {
  switch (status) {
    case "running":
      return <Loader2 className={cn(size, "animate-spin text-primary")} />
    case "done":
      return <CheckCircle className={cn(size, "text-profit")} />
    case "error":
      return <XCircle className={cn(size, "text-loss")} />
    case "skipped":
      return <Clock className={cn(size, "text-muted-foreground")} />
    case "gate":
      return <Hand className={cn(size, "text-amber-500 animate-pulse")} />
    case "data":
      return <Database className={cn(size, "text-blue-400")} />
    default:
      return <Clock className={cn(size, "text-muted-foreground/40")} />
  }
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

  return (
    <div className="space-y-1">
      {stepOrder.map((step, i) => {
        const ev = latestByStep.get(step)
        const isActive = ev?.status === "running"
        const isGate = ev?.status === "gate"
        const elapsed = stepElapsed.get(step)

        return (
          <div key={step}>
            <div
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors",
                isActive && "bg-primary/5 border border-primary/20",
                isGate && "bg-amber-500/5 border border-amber-500/30",
                !isActive && !isGate && "border border-transparent",
              )}
            >
              {ev ? stepIcon(ev.status) : stepIcon("pending")}
              <div className="flex-1 min-w-0">
                <p
                  className={cn(
                    "text-sm font-medium",
                    ev ? "text-foreground" : "text-muted-foreground/50",
                    isActive && "text-primary",
                    isGate && "text-amber-400",
                  )}
                >
                  {stepLabels[step] || step}
                </p>
                {ev?.message && (
                  <p className="text-xs text-muted-foreground truncate">{ev.message}</p>
                )}
              </div>
              {elapsed !== undefined && (
                <span className="text-[10px] text-muted-foreground/60 tabular-nums">
                  {formatElapsed(elapsed)}
                </span>
              )}
              {isActive && (
                <ArrowRight className="h-3.5 w-3.5 text-primary animate-pulse" />
              )}
              {isGate && (
                <Badge variant="default" className="bg-amber-500/20 text-amber-400 border-amber-500/30 text-[9px]">
                  REVIEW
                </Badge>
              )}
              {ev?.status === "data" && ev.gate_data && (
                <Eye className="h-3.5 w-3.5 text-blue-400" />
              )}
            </div>
            {i < stepOrder.length - 1 && (
              <div className="ml-5 h-2 border-l border-border/40" />
            )}
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
    <div className="rounded-lg border border-blue-500/20 bg-blue-500/[0.02] mt-1">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-2 px-3 py-1.5 text-left">
        <Eye className="h-3 w-3 text-blue-400" />
        <span className="text-[11px] text-blue-400 font-medium">{event.step} data</span>
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

// AutoModeToggle — commented out for now, will re-enable later
// function AutoModeToggle() { ... }

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
    <div
      className={cn(
        "rounded-xl border-2 p-4 transition-all",
        enabled
          ? "border-blue-500/60 bg-blue-500/5"
          : "border-border/60 bg-card",
      )}
    >
      <div className="flex items-center gap-3">
        <div className={cn(
          "flex items-center justify-center h-9 w-9 rounded-lg shrink-0",
          enabled ? "bg-blue-500/15" : "bg-muted/60",
        )}>
          {enabled
            ? <Hand className="h-5 w-5 text-blue-400" />
            : <Eye className="h-5 w-5 text-muted-foreground" />
          }
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold">Review Mode</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {enabled ? "Pipeline pauses at each stage for review" : "Pipeline runs without pausing"}
          </p>
        </div>
        <button
          onClick={() => mutation.mutate(!enabled)}
          disabled={mutation.isPending}
          className={cn(
            "relative inline-flex h-6 w-10 shrink-0 cursor-pointer rounded-full border-2 transition-colors duration-200 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50",
            enabled
              ? "bg-blue-500 border-blue-500"
              : "bg-muted border-border/80",
          )}
        >
          <span
            className={cn(
              "pointer-events-none inline-block rounded-full bg-white shadow-sm transition-transform duration-200",
              enabled ? "translate-x-[17px]" : "translate-x-[1px]",
            )}
            style={{ height: 16, width: 16, marginTop: 2 }}
          />
        </button>
      </div>
    </div>
  )
}

function UserNotesPanel() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [draft, setDraft] = useState("")
  const [images, setImages] = useState<{ name: string; dataUrl: string }[]>([])
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)
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
      setDropdownOpen(false)
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

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false)
      }
    }
    if (dropdownOpen) document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [dropdownOpen])

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

  const handleClear = () => {
    clearMutation.mutate()
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
    <div className="relative" ref={dropdownRef}>
      <div
        className={cn(
          "rounded-xl border-2 p-4 transition-all",
          hasNotes
            ? "border-blue-500/40 bg-blue-500/5"
            : "border-border/60 bg-card",
        )}
      >
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className={cn(
              "flex items-center justify-center h-9 w-9 rounded-lg",
              hasNotes ? "bg-blue-500/15" : "bg-muted/60",
            )}>
              <StickyNote className={cn("h-5 w-5", hasNotes ? "text-blue-400" : "text-muted-foreground")} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <p className="text-sm font-semibold">Pipeline Notes</p>
                {hasNotes && (
                  <Badge variant="default" className="text-[10px] bg-blue-500/20 text-blue-400 border-blue-500/30">
                    ACTIVE
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                {hasNotes
                  ? "Your notes will be reviewed by the judge"
                  : "Add context for the LLM judge"}
              </p>
            </div>
          </div>

          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className={cn(
              "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors",
              dropdownOpen
                ? "border-blue-500/50 bg-blue-500/10 text-blue-400"
                : "border-border/60 bg-muted/40 text-muted-foreground hover:bg-muted/60",
            )}
          >
            {dropdownOpen ? "Close" : hasNotes ? "Edit" : "Add Notes"}
            {dropdownOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
        </div>
      </div>

      {dropdownOpen && (
        <div className="absolute left-0 right-0 top-full mt-1 z-40 rounded-xl border-2 border-blue-500/30 bg-card shadow-2xl shadow-black/40 p-4 space-y-3">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onPaste={handlePaste}
            placeholder={"Share context for the judge to consider...\n\nExamples:\n• \"NVDA earnings beat expectations, see: [link]\"\n• \"Tariff concerns in semiconductor sector\""}
            className="w-full h-32 rounded-lg bg-[#0a0a0f] border border-border/60 px-3 py-2.5 text-sm text-foreground placeholder:text-muted-foreground/40 resize-none focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20"
          />

          {images.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {images.map((img, idx) => (
                <div key={idx} className="relative group">
                  <img
                    src={img.dataUrl}
                    alt={img.name}
                    className="h-20 w-20 object-cover rounded-lg border border-border/60"
                  />
                  <button
                    onClick={() => removeImage(idx)}
                    className="absolute -top-1.5 -right-1.5 h-5 w-5 rounded-full bg-red-500 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <X className="h-3 w-3" />
                  </button>
                  <p className="text-[10px] text-muted-foreground truncate w-20 mt-0.5">{img.name}</p>
                </div>
              ))}
            </div>
          )}

          <div className="flex items-center justify-end gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={handleImageAdd}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
              className="h-8 text-xs"
            >
              <ImagePlus className="h-3 w-3 mr-1" />
              Add Image
            </Button>
            {hasNotes && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleClear}
                disabled={clearMutation.isPending}
                className="border-red-500/30 text-red-400 hover:bg-red-500/10 h-8 text-xs"
              >
                {clearMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <X className="h-3 w-3 mr-1" />}
                Clear
              </Button>
            )}
            <Button
              size="sm"
              onClick={handleSave}
              disabled={saveMutation.isPending || (!draft.trim() && images.length === 0)}
              className="bg-blue-600 hover:bg-blue-700 text-white border-blue-600 h-8 text-xs"
            >
              {saveMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Save className="h-3 w-3 mr-1" />}
              Save Notes
            </Button>
          </div>
        </div>
      )}
    </div>
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
        variant="outline"
        onClick={() => setConfirming(true)}
        className="border-red-500/30 text-red-400 hover:bg-red-500/10 hover:border-red-500/50"
      >
        <RotateCcw className="mr-2 h-4 w-4" />
        Start Over
      </Button>

      {confirming && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border-2 border-red-500/40 bg-card p-6 shadow-2xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="flex items-center justify-center h-10 w-10 rounded-full bg-red-500/15">
                <Trash2 className="h-6 w-6 text-red-500" />
              </div>
              <div>
                <h3 className="text-lg font-semibold">Start Over?</h3>
                <p className="text-sm text-muted-foreground">This will delete all trading data</p>
              </div>
            </div>

            <div className="rounded-lg bg-red-500/10 border border-red-500/20 p-3 mb-4">
              <p className="text-xs font-semibold text-red-400 mb-2">The following will be permanently deleted:</p>
              <ul className="text-xs text-red-200/80 space-y-1 list-disc list-inside">
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
                className="rounded border-border/60 bg-muted accent-primary h-4 w-4"
              />
              <span className="text-sm text-muted-foreground">Keep price & fundamental data (recommended)</span>
            </label>

            <div className="flex gap-3">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => setConfirming(false)}
              >
                Cancel
              </Button>
              <Button
                className="flex-1 bg-red-600 hover:bg-red-700 text-white border-red-600"
                onClick={() => mutation.mutate()}
                disabled={mutation.isPending}
              >
                {mutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="mr-2 h-4 w-4" />
                )}
                Delete & Reset
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export default function PipelineControl() {
  const { running, events, error, activeGate, lastCompletedRunId, startPipeline, respondToGate } = usePipeline()
  const { toast } = useToast()
  const navigate = useNavigate()
  const logRef = useRef<HTMLDivElement>(null)
  const prevEventsLen = useRef(0)
  const eventTimestamps = useRef<Map<number, number>>(new Map())

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

  return (
    <>
      <PageHeader
        title="Pipeline Control"
        description="Manually trigger the EOD pipeline and watch progress in real-time"
        actions={
          <div className="flex items-center gap-3">
            {isComplete && <Badge variant="profit">Complete</Badge>}
            {hasError && <Badge variant="loss">Error</Badge>}
            {error && <Badge variant="loss">{error}</Badge>}
            <StartOverButton />
            <Button
              variant="outline"
              onClick={startPipeline}
              disabled={running}
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
                  Run Pipeline
                </>
              )}
            </Button>
          </div>
        }
      />

      {running && (
        <div className="mb-6">
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-2">
            <span>Pipeline progress</span>
            <span>{completedSteps} / {stepOrder.length - 1} steps</span>
          </div>
          <div className="h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              className="h-full rounded-full bg-primary transition-all duration-500 ease-out"
              style={{ width: `${(completedSteps / (stepOrder.length - 1)) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Pipeline completed banner */}
      {isComplete && !hasError && !running && (
        <div className="mb-4 rounded-xl border-2 border-profit/40 bg-profit/5 p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center h-9 w-9 rounded-lg bg-profit/15">
                <CheckCircle className="h-5 w-5 text-profit" />
              </div>
              <div>
                <p className="text-sm font-semibold">Pipeline Complete</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {events.find((e) => e.step === "complete")?.message || "All steps finished successfully"}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate("/")}
                className="h-8 text-xs"
              >
                Portfolio
                <ExternalLink className="ml-1.5 h-3 w-3" />
              </Button>
              <Button
                size="sm"
                onClick={() => navigate("/trades")}
                className="bg-profit/90 hover:bg-profit text-white border-profit h-8 text-xs"
              >
                View Trades
                <ArrowRight className="ml-1.5 h-3 w-3" />
              </Button>
            </div>
          </div>
        </div>
      )}

      <div className="mb-4">
        <div className="grid grid-cols-2 gap-3">
          <UserNotesPanel />
          <ReviewModeToggle />
        </div>
      </div>

      {/* Active Gate Review Panel */}
      {activeGate && (
        <div className="mb-4">
          <GateReviewPanel
            gate={activeGate}
            onContinue={(overrides) => respondToGate("continue", overrides)}
            onAbort={() => respondToGate("abort")}
          />
        </div>
      )}

      <div className="grid grid-cols-3 gap-6">
        <Card className="col-span-1">
          <CardTitle>Steps</CardTitle>
          <CardContent>
            <StepTracker events={events} eventTimestamps={eventTimestamps.current} />
          </CardContent>
        </Card>

        <Card className="col-span-2">
          <CardTitle>Live Log</CardTitle>
          <CardContent>
            <div
              ref={logRef}
              className="h-[28rem] overflow-y-auto rounded-lg bg-[#0a0a0f] border border-border/40 p-4 font-mono text-xs space-y-0.5"
            >
              {events.length === 0 ? (
                <p className="text-muted-foreground/50">
                  Click "Run Pipeline" to start...
                </p>
              ) : (
                events.map((e, i) => (
                  <div key={i}>
                    <div className="flex gap-2 py-0.5">
                      <span className="text-muted-foreground/60 w-24 shrink-0 text-right">
                        [{e.step}]
                      </span>
                      <span
                        className={cn(
                          e.status === "error"
                            ? "text-loss"
                            : e.status === "done"
                              ? "text-profit"
                              : e.status === "running"
                                ? "text-primary"
                                : e.status === "gate"
                                  ? "text-amber-400"
                                  : e.status === "data"
                                    ? "text-blue-400"
                                    : "text-foreground/70",
                        )}
                      >
                        {e.status === "gate" && "⏸ "}
                        {e.status === "data" && "📊 "}
                        {e.message}
                      </span>
                    </div>
                    {e.status === "data" && e.gate_data && (
                      <StepDataDisplay event={e} />
                    )}
                  </div>
                ))
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  )
}
