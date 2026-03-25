import { createContext, useContext, useState, useCallback, useRef, type ReactNode } from "react"

export interface PipelineEvent {
  step: string
  status: string
  message: string
  summary?: Record<string, unknown>
}

interface PipelineState {
  running: boolean
  events: PipelineEvent[]
  error: string | null
  runId: string | null
  startPipeline: () => Promise<void>
}

const PipelineContext = createContext<PipelineState | null>(null)

export function PipelineProvider({ children }: { children: ReactNode }) {
  const [running, setRunning] = useState(false)
  const [events, setEvents] = useState<PipelineEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const esRef = useRef<EventSource | null>(null)

  const startPipeline = useCallback(async () => {
    if (running) return

    setRunning(true)
    setEvents([])
    setError(null)

    try {
      const res = await fetch("/api/pipeline/run", { method: "POST" })
      if (!res.ok) throw new Error(`Failed to start pipeline: ${res.status}`)
      const data = await res.json()
      setRunId(data.run_id)

      const es = new EventSource(`/api/pipeline/status?run_id=${data.run_id}`)
      esRef.current = es

      es.onmessage = (event) => {
        const parsed: PipelineEvent = JSON.parse(event.data)
        setEvents((prev) => [...prev, parsed])
        if (parsed.step === "complete" || parsed.status === "error") {
          es.close()
          esRef.current = null
          setRunning(false)
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

  return (
    <PipelineContext.Provider value={{ running, events, error, runId, startPipeline }}>
      {children}
    </PipelineContext.Provider>
  )
}

export function usePipeline() {
  const ctx = useContext(PipelineContext)
  if (!ctx) throw new Error("usePipeline must be used within PipelineProvider")
  return ctx
}
