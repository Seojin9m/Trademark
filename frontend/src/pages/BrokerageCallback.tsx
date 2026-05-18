import { useEffect, useState } from "react"

/**
 * Landing page for SnapTrade's customRedirect after the user finishes the
 * brokerage OAuth grant. The page exists only to close the popup window —
 * the parent (AuthConnectBrokerage) polls ``popup.closed`` and fires the
 * post-connect sync once we close.
 *
 * Falls back to a "you can close this tab" message if window.close() is
 * blocked (browsers refuse window.close on tabs the script didn't open).
 */
export default function BrokerageCallback() {
  const [closed, setClosed] = useState(false)

  useEffect(() => {
    // Defer one tick so React paints the placeholder first — gives the
    // user something to see if window.close is blocked.
    const t = setTimeout(() => {
      try {
        window.close()
        setClosed(true)
      } catch {
        setClosed(false)
      }
    }, 80)
    return () => clearTimeout(t)
  }, [])

  const params = new URLSearchParams(window.location.search)
  const status = params.get("status")

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-8 text-center">
      <div className="max-w-sm space-y-3">
        <div className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">
          ◆ BROKERAGE CONNECT
        </div>
        <h2 className="text-[22px] font-semibold tracking-[-0.02em]">
          {status === "SUCCESS" ? "Connected." : "Returned from brokerage."}
        </h2>
        <p className="text-[13px] text-muted-foreground">
          {closed
            ? "Closing this window…"
            : "You can close this window — the app will pick up the connection automatically."}
        </p>
      </div>
    </div>
  )
}
