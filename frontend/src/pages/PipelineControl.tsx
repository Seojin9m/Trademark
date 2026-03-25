import { useEffect, useRef } from "react"
import { usePipeline } from "@/contexts/pipeline-context"
import { useToast } from "@/contexts/toast-context"
import type { PipelineEvent } from "@/contexts/pipeline-context"
import { PageHeader } from "@/components/layout/page-header"
import { Card, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Play, Loader2, CheckCircle, XCircle, Clock, ArrowRight } from "lucide-react"
import { cn } from "@/lib/utils"

const stepOrder = ["ingestion", "scoring", "signals", "proposals", "research", "judge", "pnl", "complete"]

const stepLabels: Record<string, string> = {
  ingestion: "Data Ingestion",
  scoring: "Factor Scoring",
  signals: "Signal Generation",
  proposals: "Trade Proposals",
  research: "News Research",
  judge: "LLM Judge",
  pnl: "P&L Update",
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

export default function PipelineControl() {
  const { running, events, error, startPipeline } = usePipeline()
  const { toast } = useToast()
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
            <Button onClick={startPipeline} disabled={running} size="lg">
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
