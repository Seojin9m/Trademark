import { useEffect, useRef, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { usePipeline } from "@/contexts/pipeline-context"
import { useToast } from "@/contexts/toast-context"
import type { PipelineEvent } from "@/contexts/pipeline-context"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Play, Loader2, CheckCircle, XCircle, Clock, ArrowRight, AlertTriangle, ShieldAlert, Zap, Trash2, RotateCcw } from "lucide-react"
import { cn } from "@/lib/utils"
import { api } from "@/lib/api"

const stepOrder = ["ingestion", "scoring", "adaptive", "signals", "proposals", "research", "judge", "execution", "pnl", "learning", "complete"]

const stepLabels: Record<string, string> = {
  ingestion: "Data Ingestion",
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
    default:
      return <Clock className={cn(size, "text-muted-foreground/40")} />
  }
}

function StepTracker({ events }: { events: PipelineEvent[] }) {
  const latestByStep = new Map<string, PipelineEvent>()
  events.forEach((e) => latestByStep.set(e.step, e))

  return (
    <div className="space-y-1">
      {stepOrder.map((step, i) => {
        const ev = latestByStep.get(step)
        const isActive = ev?.status === "running"

        return (
          <div key={step}>
            <div
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors",
                isActive && "bg-primary/5 border border-primary/20",
                !isActive && "border border-transparent",
              )}
            >
              {ev ? stepIcon(ev.status) : stepIcon("pending")}
              <div className="flex-1 min-w-0">
                <p
                  className={cn(
                    "text-sm font-medium",
                    ev ? "text-foreground" : "text-muted-foreground/50",
                    isActive && "text-primary",
                  )}
                >
                  {stepLabels[step] || step}
                </p>
                {ev?.message && (
                  <p className="text-xs text-muted-foreground truncate">{ev.message}</p>
                )}
              </div>
              {isActive && (
                <ArrowRight className="h-3.5 w-3.5 text-primary animate-pulse" />
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

function AutoModeToggle() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [confirming, setConfirming] = useState(false)

  const { data: autoMode } = useQuery({
    queryKey: ["auto-mode"],
    queryFn: api.getAutoMode,
    refetchInterval: 5000,
  })

  const mutation = useMutation({
    mutationFn: api.setAutoMode,
    onSuccess: (data) => {
      queryClient.setQueryData(["auto-mode"], data)
      toast(
        data.enabled ? "info" : "success",
        data.enabled ? "Auto Mode Enabled" : "Auto Mode Disabled",
        data.enabled
          ? "Trades will be executed automatically without review"
          : "Trades will require manual approval",
      )
      setConfirming(false)
    },
  })

  const enabled = autoMode?.enabled ?? false

  const handleToggle = () => {
    if (!enabled) {
      // Turning ON — require confirmation
      setConfirming(true)
    } else {
      // Turning OFF — do it immediately
      mutation.mutate(false)
    }
  }

  return (
    <div className="relative">
      <div
        className={cn(
          "rounded-xl border-2 p-4 transition-all",
          enabled
            ? "border-amber-500/60 bg-amber-500/5"
            : "border-border/60 bg-card",
        )}
      >
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            {enabled ? (
              <div className="flex items-center justify-center h-9 w-9 rounded-lg bg-amber-500/15">
                <Zap className="h-5 w-5 text-amber-500" />
              </div>
            ) : (
              <div className="flex items-center justify-center h-9 w-9 rounded-lg bg-muted/60">
                <ShieldAlert className="h-5 w-5 text-muted-foreground" />
              </div>
            )}
            <div>
              <div className="flex items-center gap-2">
                <p className="text-sm font-semibold">Auto Mode</p>
                <Badge variant={enabled ? "loss" : "muted"} className="text-[10px]">
                  {enabled ? "ACTIVE" : "OFF"}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                {enabled
                  ? "Trades are executed automatically after judge approval"
                  : "Trades require manual review before execution"}
              </p>
            </div>
          </div>

          <button
            onClick={handleToggle}
            disabled={mutation.isPending}
            className={cn(
              "relative inline-flex h-7 w-12 shrink-0 cursor-pointer rounded-full border-2 transition-colors duration-200 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50",
              enabled
                ? "bg-amber-500 border-amber-500"
                : "bg-muted border-border/80",
            )}
          >
            <span
              className={cn(
                "pointer-events-none inline-block h-5.5 w-5.5 rounded-full bg-white shadow-sm transition-transform duration-200 mt-[1px]",
                enabled ? "translate-x-[22px]" : "translate-x-[2px]",
              )}
              style={{ height: 20, width: 20 }}
            />
          </button>
        </div>

        {enabled && (
          <div className="mt-3 flex items-start gap-2 rounded-lg bg-amber-500/10 border border-amber-500/20 px-3 py-2">
            <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
            <div className="text-xs text-amber-200/80 leading-relaxed">
              <span className="font-semibold text-amber-400">Warning:</span> Auto mode will
              execute all judge-approved trades immediately without human confirmation.
              Real portfolio changes will be made. Only use this if you trust the model's decisions.
            </div>
          </div>
        )}
      </div>

      {/* Confirmation modal */}
      {confirming && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border-2 border-amber-500/40 bg-card p-6 shadow-2xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="flex items-center justify-center h-10 w-10 rounded-full bg-amber-500/15">
                <AlertTriangle className="h-6 w-6 text-amber-500" />
              </div>
              <div>
                <h3 className="text-lg font-semibold">Enable Auto Mode?</h3>
                <p className="text-sm text-muted-foreground">This action requires confirmation</p>
              </div>
            </div>

            <div className="rounded-lg bg-amber-500/10 border border-amber-500/20 p-3 mb-5">
              <ul className="text-xs text-amber-200/80 space-y-1.5 list-disc list-inside">
                <li>All judge-approved trades will be executed <span className="font-semibold text-amber-400">immediately</span></li>
                <li>No human review step — the model decides for you</li>
                <li>Portfolio state (cash, positions) will be modified automatically</li>
                <li>Judge-rejected trades will still be blocked</li>
              </ul>
            </div>

            <div className="flex gap-3">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => setConfirming(false)}
              >
                Cancel
              </Button>
              <Button
                className="flex-1 bg-amber-600 hover:bg-amber-700 text-white border-amber-600"
                onClick={() => mutation.mutate(true)}
                disabled={mutation.isPending}
              >
                {mutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Zap className="mr-2 h-4 w-4" />
                )}
                Enable Auto Mode
              </Button>
            </div>
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
                <li>Portfolio reset to $100k cash, no positions</li>
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
  const { running, events, error, startPipeline } = usePipeline()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const logRef = useRef<HTMLDivElement>(null)
  const prevEventsLen = useRef(0)

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

      <div className="mb-4">
        <AutoModeToggle />
      </div>

      <div className="grid grid-cols-3 gap-6">
        <Card className="col-span-1">
          <CardTitle>Steps</CardTitle>
          <CardContent>
            <StepTracker events={events} />
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
                  <div key={i} className="flex gap-2 py-0.5">
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
                              : "text-foreground/70",
                      )}
                    >
                      {e.message}
                    </span>
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
