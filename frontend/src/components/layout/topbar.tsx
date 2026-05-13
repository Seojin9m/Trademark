import { useLocation } from "react-router-dom"
import { useEffect, useState } from "react"

const PAGE_LABELS: Record<string, string> = {
  "/": "PORTFOLIO",
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
}

export function Topbar() {
  const { pathname } = useLocation()
  const pageLabel = PAGE_LABELS[pathname] ?? "PORTFOLIO"

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
      </div>
    </div>
  )
}
