import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react"
import { X, AlertCircle, CheckCircle, Info } from "lucide-react"
import { cn } from "@/lib/utils"
import { registerGlobalToast } from "@/main"

type ToastType = "error" | "success" | "info"

interface Toast {
  id: number
  type: ToastType
  title: string
  message?: string
}

interface ToastContextValue {
  toast: (type: ToastType, title: string, message?: string) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

let nextId = 0

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const addToast = useCallback((type: ToastType, title: string, message?: string) => {
    const id = nextId++
    setToasts((prev) => [...prev, { id, type, title, message }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 6000)
  }, [])

  // Register globally so QueryClient can fire toasts
  useEffect(() => {
    registerGlobalToast(addToast)
  }, [addToast])

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const Icon = { error: AlertCircle, success: CheckCircle, info: Info }

  return (
    <ToastContext.Provider value={{ toast: addToast }}>
      {children}

      {/* Toast container */}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
        {toasts.map((t) => {
          const IconComp = Icon[t.type]
          return (
            <div
              key={t.id}
              className={cn(
                "flex items-start gap-3 rounded-xl border px-4 py-3 shadow-lg animate-fade-in backdrop-blur-sm",
                t.type === "error" && "bg-loss/10 border-loss/30 text-loss",
                t.type === "success" && "bg-profit/10 border-profit/30 text-profit",
                t.type === "info" && "bg-primary/10 border-primary/30 text-primary",
              )}
            >
              <IconComp className="h-4 w-4 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium">{t.title}</p>
                {t.message && (
                  <p className="text-xs opacity-80 mt-0.5 break-words">{t.message}</p>
                )}
              </div>
              <button
                onClick={() => dismiss(t.id)}
                className="shrink-0 opacity-60 hover:opacity-100 transition-opacity"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error("useToast must be used within ToastProvider")
  return ctx
}
