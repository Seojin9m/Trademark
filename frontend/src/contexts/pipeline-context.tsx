import { createContext, useContext, useState, useCallback, useRef, type ReactNode } from "react"
import type { PipelineRunParams } from "../lib/api"

export interface PipelineEvent {
  step: string
  status: string
  message: string
  summary?: Record<string, unknown>
  gate_data?: Record<string, unknown>
  gate_name?: string
}

interface PipelineState {
  running: boolean
  events: PipelineEvent[]
  error: string | null
  runId: string | null
  activeGate: PipelineEvent | null
  lastCompletedRunId: string | null
  clearLastCompletedRunId: () => void
  startPipeline: (params?: PipelineRunParams) => Promise<void>
  respondToGate: (action: "continue" | "abort", overrides?: Record<string, unknown>) => Promise<void>
}

const PipelineContext = createContext<PipelineState | null>(null)

export function PipelineProvider({ children }: { children: ReactNode }) {
  const [running, setRunning] = useState(false)
  const [events, setEvents] = useState<PipelineEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [activeGate, setActiveGate] = useState<PipelineEvent | null>(null)
  const [lastCompletedRunId, setLastCompletedRunId] = useState<string | null>(null)
  const esRef = useRef<EventSource | null>(null)
  const runIdRef = useRef<string | null>(null)

  const clearLastCompletedRunId = useCallback(() => setLastCompletedRunId(null), [])

  const startPipeline = useCallback(async (params?: PipelineRunParams) => {
    if (running) return

    setRunning(true)
    setEvents([])
    setError(null)
    setActiveGate(null)

    try {
      const res = await fetch("/api/pipeline/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params ?? {}),
      })
      if (!res.ok) throw new Error(`Failed to start pipeline: ${res.status}`)
      const data = await res.json()
      setRunId(data.run_id)
      runIdRef.current = data.run_id

      const es = new EventSource(`/api/pipeline/status?run_id=${data.run_id}`)
      esRef.current = es

      es.onmessage = (event) => {
        const parsed: PipelineEvent = JSON.parse(event.data)
        setEvents((prev) => [...prev, parsed])

        if (parsed.status === "gate") {
          setActiveGate(parsed)
        } else if (parsed.status === "done" || parsed.status === "error" || parsed.status === "running") {
          // Any progress after a gate means the gate was resolved
          setActiveGate((prev) => (prev && prev.step === parsed.step ? null : prev))
        }

        if (parsed.step === "complete") {
          es.close()
          esRef.current = null
          setRunning(false)
          setActiveGate(null)
          if (parsed.status === "done") {
            setLastCompletedRunId(runIdRef.current)
          }
        }
      }

      es.onerror = () => {
        es.close()
        esRef.current = null
        setRunning(false)
        setError("Connection to pipeline lost")
      }
    } catch (e) {
      setError(String(e))
      setRunning(false)
    }
  }, [running])

  const respondToGate = useCallback(async (action: "continue" | "abort", overrides?: Record<string, unknown>) => {
    if (!activeGate || !runIdRef.current) return

    try {
      await fetch("/api/pipeline/gate/respond", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: runIdRef.current,
          gate_name: activeGate.gate_name,
          action,
          overrides: overrides ?? {},
        }),
      })
      setActiveGate(null)
    } catch (e) {
      setError(`Failed to respond to gate: ${e}`)
    }
  }, [activeGate])

  return (
    <PipelineContext.Provider value={{ running, events, error, runId, activeGate, lastCompletedRunId, clearLastCompletedRunId, startPipeline, respondToGate }}>
      {children}
    </PipelineContext.Provider>
  )
}

export function usePipeline() {
  const ctx = useContext(PipelineContext)
  if (!ctx) throw new Error("usePipeline must be used within PipelineProvider")
  return ctx
}
