import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider, QueryCache, MutationCache } from "@tanstack/react-query"
import { AuthProvider } from "./contexts/auth-context"
import { PipelineProvider } from "./contexts/pipeline-context"
import { AnalystProvider } from "./contexts/analyst-context"
import { ToastProvider } from "./contexts/toast-context"
import "./index.css"
import App from "./App"

// Global toast emitter — bridges QueryClient (outside React) with ToastProvider (inside React)
type ToastFn = (type: "error" | "success" | "info", title: string, message?: string) => void
let _globalToast: ToastFn | null = null
export function registerGlobalToast(fn: ToastFn) { _globalToast = fn }

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: 60_000,
      retry: 1,
      staleTime: 30_000,
    },
  },
  queryCache: new QueryCache({
    onError: (error, query) => {
      // Only toast for queries that have already been shown (avoid initial load spam)
      if (query.state.data !== undefined) {
        _globalToast?.("error", "Data Fetch Failed", String(error))
      }
    },
  }),
  mutationCache: new MutationCache({
    onError: (error) => {
      _globalToast?.("error", "Action Failed", String(error))
    },
  }),
})

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <ToastProvider>
            <PipelineProvider>
              <AnalystProvider>
                <App />
              </AnalystProvider>
            </PipelineProvider>
          </ToastProvider>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
