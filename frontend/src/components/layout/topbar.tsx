import { useLocation } from "react-router-dom"
import { useEffect, useRef, useState } from "react"
import { LogOut, ChevronDown } from "lucide-react"
import { useAuth } from "@/contexts/auth-context"
import { cn } from "@/lib/utils"

const PAGE_LABELS: Record<string, string> = {
  "/": "RANKINGS",
  "/portfolio": "PORTFOLIO",
  "/analyst": "ANALYST",
  "/signals": "SIGNALS",
  "/trades": "TRADES",
  "/decisions": "DECISIONS",
  "/risk": "RISK",
  "/data": "DATA GRID",
  "/research": "RESEARCH",
  "/learning": "LEARNING",
  "/backtest": "BACKTEST",
  "/brokerage": "BROKERAGE",
  "/pipeline": "PIPELINE",
  "/watchlist": "WATCHLIST",
}

export function Topbar() {
  const { pathname } = useLocation()
  const pageLabel = PAGE_LABELS[pathname] ?? "TRADEMARK"

  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000)
    return () => clearInterval(t)
  }, [])

  const time = now.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "America/New_York",
  })

  const isMarketOpen = (() => {
    const et = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }))
    const day = et.getDay()
    const hours = et.getHours()
    const mins = et.getMinutes()
    const totalMins = hours * 60 + mins
    return day >= 1 && day <= 5 && totalMins >= 570 && totalMins < 960
  })()

  return (
    <div className="sticky top-0 z-30 flex h-10 items-center gap-[18px] border-b border-line bg-bg-2/80 px-[18px] backdrop-blur-md">
      {/* Breadcrumbs */}
      <div className="font-mono text-[11px] tracking-[0.02em] text-muted-foreground">
        <span>TRADEMARK</span>
        <span className="mx-2 text-line-2">/</span>
        <span className="text-foreground">{pageLabel}</span>
      </div>

      {/* Market status — right aligned */}
      <div className="ml-auto flex items-center gap-[18px] font-mono text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${isMarketOpen ? "bg-profit animate-pulse-dot" : "bg-loss"}`}
          />
          <span>Markets </span>
          <span className={isMarketOpen ? "text-profit" : "text-loss"}>
            {isMarketOpen ? "OPEN" : "CLOSED"}
          </span>
        </span>
        <span>{time} ET</span>
        <UserMenu />
      </div>
    </div>
  )
}

function UserMenu() {
  const { user, signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener("mousedown", onClick)
    return () => window.removeEventListener("mousedown", onClick)
  }, [open])

  if (!user) return null
  const initials = (user.email || "?").slice(0, 2).toUpperCase()

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-1.5 rounded-[4px] border border-line-2 px-1.5 py-1 transition-colors hover:bg-surface",
          open && "bg-surface",
        )}
      >
        <span className="flex h-5 w-5 items-center justify-center rounded-[3px] bg-primary/15 font-mono text-[9.5px] font-bold uppercase text-primary">
          {initials}
        </span>
        <ChevronDown className="h-3 w-3 text-muted-foreground" />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-40 mt-1.5 w-[220px] overflow-hidden rounded-[6px] border border-line-2 bg-surface shadow-lg">
          <div className="border-b border-line px-3 py-2.5">
            <div className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-muted-2">
              SIGNED IN AS
            </div>
            <div className="truncate font-mono text-[11.5px] text-foreground">{user.email}</div>
          </div>
          <button
            onClick={async () => {
              setOpen(false)
              await signOut()
              // signOut clears the session; AuthProvider's onAuthStateChange will
              // notify the App and re-render into the AuthFlow.
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-[12px] text-loss transition-colors hover:bg-loss/8"
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}
