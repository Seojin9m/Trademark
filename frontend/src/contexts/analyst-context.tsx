import { createContext, useContext, useState, useCallback, useRef, useEffect, type ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { AnalystReview } from "@/lib/api"
import { useToast } from "./toast-context"

const TOTAL_STEPS = 10
const STEP_INTERVAL_MS = 1800

interface AnalystState {
  analyzing: boolean
  error: string | null
  visibleSteps: number
  requestAnalysis: () => void
}

const AnalystContext = createContext<AnalystState | null>(null)

export function AnalystProvider({ children }: { children: ReactNode }) {
  const [analyzing, setAnalyzing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [visibleSteps, setVisibleSteps] = useState(0)
  const queryClient = useQueryClient()
  const toastRef = useRef<ReturnType<typeof useToast> | null>(null)
  const toast = useToast()
  toastRef.current = toast

  useEffect(() => {
    if (!analyzing) return
    const id = setInterval(() => {
      setVisibleSteps((n) => (n < TOTAL_STEPS ? n + 1 : n))
    }, STEP_INTERVAL_MS)
    return () => clearInterval(id)
  }, [analyzing])

  const requestAnalysis = useCallback(async () => {
    if (analyzing) return
    setAnalyzing(true)
    setError(null)
    setVisibleSteps(1)
    try {
      const review: AnalystReview = await api.requestAnalystReview()
      queryClient.setQueryData(["analyst-review"], { review })
      toastRef.current?.toast(
        "success",
        "Analysis Complete",
        `Stance: ${review.overall_stance} · Health: ${review.portfolio_health_score}/100`,
      )
    } catch (e) {
      const msg = e instanceof Error ? e.message.replace(/^Error:\s*/, "") : String(e)
      setError(msg)
      toastRef.current?.toast("error", "Analysis Failed", msg)
    } finally {
      setAnalyzing(false)
      setVisibleSteps(0)
    }
  }, [analyzing, queryClient])

  return (
    <AnalystContext.Provider value={{ analyzing, error, visibleSteps, requestAnalysis }}>
      {children}
    </AnalystContext.Provider>
  )
}

export function useAnalyst() {
  const ctx = useContext(AnalystContext)
  if (!ctx) throw new Error("useAnalyst must be used within AnalystProvider")
  return ctx
}
