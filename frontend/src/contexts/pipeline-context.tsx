import { createContext, useContext, useState, useCallback, useRef, type ReactNode } from "react"
import type { PipelineRunParams } from "../lib/api"
import { buildAuthHeaders, apiUrl, appTokenQuery } from "@/lib/utils"

// The pipeline POSTs don't go through apiFetch because of the 409-recovery
// path (apiFetch would throw before we could read the body), so we build the
// same auth headers (X-App-Token + Supabase JWT) manually here.
async function authHeaders(): Promise<HeadersInit> {
  const h = await buildAuthHeaders({ "Content-Type": "application/json" })
  return h
}

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
      const res = await fetch(apiUrl("/pipeline/run"), {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify(params ?? {}),
      })

      let activeRunId: string | null = null
      if (res.status === 409) {
        // Backend says a pipeline is already running. Resubscribe to it
        // instead of failing — this is the recovery path when the SSE
        // dropped (uvicorn --reload, network blip) but the pipeline is
        // still alive on the server.
        const body = await res.json()
        activeRunId = body?.detail?.run_id ?? null
        if (!activeRunId) throw new Error("Pipeline already running but no run_id returned")
      } else if (!res.ok) {
        throw new Error(`Failed to start pipeline: ${res.status}`)
      } else {
        const data = await res.json()
        activeRunId = data.run_id
      }

      setRunId(activeRunId)
      runIdRef.current = activeRunId

      // EventSource can't set headers, so the app token rides in the query
      // string. The backend middleware accepts either header or ?app_token.
      const q = appTokenQuery()
      const statusUrl = apiUrl(`/pipeline/status?run_id=${activeRunId}${q ? `&${q}` : ""}`)
      const es = new EventSource(statusUrl)
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
      await fetch(apiUrl("/pipeline/gate/respond"), {
        method: "POST",
        headers: await authHeaders(),
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
