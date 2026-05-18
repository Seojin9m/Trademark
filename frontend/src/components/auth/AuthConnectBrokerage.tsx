import { useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { Loader2, RefreshCw, ShieldCheck } from "lucide-react"
import { api } from "@/lib/api"
import { useAuth } from "@/contexts/auth-context"
import { AuthBrandPanel } from "./AuthBrandPanel"
import { AuthStepper } from "./AuthStepper"
import { cn } from "@/lib/utils"

type Mode = "login" | "signup"

interface Props {
  mode: Mode
  onConnected: () => void
  onBack: () => void
}

interface BrokerOption {
  id: string
  name: string
  desc: string
  tag: string | null
  status: "live" | "soon"
  accent: string
}

const BROKERS: BrokerOption[] = [
  { id: "WEALTHSIMPLETRADE", name: "Wealthsimple", desc: "CA · Stocks, Options, Crypto", tag: "RECOMMENDED", status: "live", accent: "#2A9D8F" },
  { id: "schwab", name: "Charles Schwab", desc: "US · Equities, Options, ETFs", tag: null, status: "soon", accent: "#0099D8" },
  { id: "fidelity", name: "Fidelity", desc: "US · Equities, Options, MF", tag: null, status: "soon", accent: "#3CB04A" },
  { id: "ibkr", name: "Interactive Brokers", desc: "Global · 150+ markets", tag: null, status: "soon", accent: "#D81E2A" },
  { id: "robin", name: "Robinhood", desc: "US · Equities, Crypto", tag: null, status: "soon", accent: "#CFFF00" },
  { id: "qt", name: "Questrade", desc: "CA · Equities, Options", tag: null, status: "soon", accent: "#1C8F3A" },
]

type Phase = "pick" | "oauth" | "done"

/**
 * Step 3 (signup) / Step 2 (login): brokerage connect via SnapTrade OAuth.
 *
 * The flow:
 *   1. User picks a broker → we hit POST /api/brokerage/connect, which returns
 *      a SnapTrade redirect URL.
 *   2. We open the URL in a popup; the user grants permissions in the
 *      brokerage's site; SnapTrade redirects back. (For the demo, the popup
 *      auto-closes after a few seconds.)
 *   3. We call POST /api/brokerage/sync to pull positions, then mark the user
 *      onboarded via supabase.auth.updateUser (auth-context flips
 *      brokerageConnected = true).
 */
export function AuthConnectBrokerage({ mode, onConnected, onBack }: Props) {
  const { markBrokerageConnected } = useAuth()
  const [phase, setPhase] = useState<Phase>("pick")
  const [selectedId, setSelectedId] = useState<string | null>("WEALTHSIMPLETRADE")
  const [error, setError] = useState<string | null>(null)

  const broker = BROKERS.find((b) => b.id === selectedId)

  const connectMutation = useMutation({
    mutationFn: (id: string) => api.connectBrokerage(id),
  })

  const startConnect = async () => {
    if (!broker || broker.status !== "live") return
    setError(null)
    setPhase("oauth")
    try {
      const { url } = await connectMutation.mutateAsync(broker.id)
      // Open the OAuth flow in a popup. The user finishes in the brokerage's
      // site; on success they'll be redirected to /brokerage/callback in the
      // backend, which closes the popup.
      const popup = window.open(url, "snaptrade", "width=520,height=720")
      const poll = window.setInterval(async () => {
        if (popup?.closed) {
          window.clearInterval(poll)
          try {
            await api.syncPortfolio()
            await markBrokerageConnected()
            setPhase("done")
            setTimeout(onConnected, 700)
          } catch (e) {
            setError(e instanceof Error ? e.message : "Sync failed after connect")
            setPhase("pick")
          }
        }
      }, 800)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start OAuth")
      setPhase("pick")
    }
  }

  const stepLabel = mode === "signup" ? "STEP 3 OF 3" : "STEP 2 OF 2"

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <AuthBrandPanel variant="brokerage" />
      <div className="flex flex-1 items-center justify-center px-6 py-10 sm:px-10">
        <div className="w-full max-w-[560px]">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-muted-foreground">
              {stepLabel}
            </span>
            {phase === "pick" && (
              <button
                onClick={onBack}
                className="rounded-[4px] border border-line-2 px-2 py-1 font-mono text-[10.5px] text-muted-foreground hover:text-foreground"
              >
                ← Back
              </button>
            )}
          </div>

          <AuthStepper current={2} mode={mode} />

          {phase === "pick" && (
            <>
              <div className="mb-5">
                <div className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  ◆ CONNECT BROKERAGE
                </div>
                <h2 className="mt-1 text-[24px] font-semibold tracking-[-0.02em]">
                  Link an account to begin trading
                </h2>
                <p className="mt-1 text-[13px] text-muted-foreground">
                  Trademark uses read-only OAuth by default. You explicitly authorize any trade
                  execution per order. Disconnect from Account settings any time.
                </p>
              </div>

              <div className="mb-5 space-y-2">
                {BROKERS.map((b) => {
                  const isSel = selectedId === b.id
                  const soon = b.status === "soon"
                  return (
                    <button
                      key={b.id}
                      type="button"
                      onClick={() => !soon && setSelectedId(b.id)}
                      disabled={soon}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-[6px] border px-3 py-2.5 text-left transition-colors",
                        soon
                          ? "cursor-not-allowed border-line bg-bg-2/40 opacity-50"
                          : isSel
                            ? "border-primary bg-primary/8"
                            : "border-line-2 bg-surface hover:bg-surface-2",
                      )}
                    >
                      <span
                        className="flex h-9 w-9 items-center justify-center rounded-[4px] font-mono text-[11px] font-bold"
                        style={{ background: `${b.accent}1a`, color: b.accent }}
                      >
                        {b.name
                          .split(" ")
                          .map((w) => w[0])
                          .slice(0, 2)
                          .join("")}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 text-[13px] font-semibold">
                          <span>{b.name}</span>
                          {b.tag && (
                            <span className="rounded-[2px] bg-primary/15 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.08em] text-primary">
                              {b.tag}
                            </span>
                          )}
                        </div>
                        <div className="font-mono text-[11px] text-muted-foreground">{b.desc}</div>
                      </div>
                      {soon ? (
                        <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-2">
                          COMING SOON
                        </span>
                      ) : (
                        <span
                          className={cn(
                            "h-4 w-4 rounded-full border-2 transition-colors",
                            isSel ? "border-primary bg-primary" : "border-line-2",
                          )}
                        />
                      )}
                    </button>
                  )
                })}
              </div>

              <div className="mb-5 space-y-2 rounded-[5px] border border-line-2 bg-bg-2 px-3 py-3">
                <TrustItem
                  icon={<ShieldCheck className="h-3.5 w-3.5" />}
                  title="Read-only by default"
                  sub="Portfolio & positions only — no trades unless you approve each one."
                />
                <TrustItem
                  icon={<RefreshCw className="h-3.5 w-3.5" />}
                  title="Revoke anytime"
                  sub="Disconnect from Account settings to revoke OAuth instantly."
                />
              </div>

              {error && (
                <div className="mb-3 rounded-[4px] border border-loss/40 bg-loss/10 px-3 py-2 text-[12px] text-loss">
                  {error}
                </div>
              )}

              <button
                onClick={startConnect}
                disabled={!broker || broker.status !== "live" || connectMutation.isPending}
                className="flex h-10 w-full items-center justify-center gap-2 rounded-[5px] bg-primary text-[13px] font-semibold text-background transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {connectMutation.isPending ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> Starting…
                  </>
                ) : broker ? (
                  `Continue with ${broker.name} →`
                ) : (
                  "Select a brokerage to continue"
                )}
              </button>
            </>
          )}

          {phase === "oauth" && (
            <div className="flex flex-col items-center gap-4 py-10 text-center">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <div>
                <div className="text-[15px] font-semibold">Connecting to {broker?.name}…</div>
                <div className="mt-1 text-[12px] text-muted-foreground">
                  Finish the connection in the popup window. We'll detect when it closes.
                </div>
              </div>
            </div>
          )}

          {phase === "done" && (
            <div className="flex flex-col items-center gap-3 py-10 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-profit/15">
                <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
                  <path d="M8 17l5 5L24 10" stroke="#7ee787" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div className="text-[18px] font-semibold">You're all set</div>
              <div className="text-[12px] text-muted-foreground">Launching your dashboard…</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function TrustItem({ icon, title, sub }: { icon: React.ReactNode; title: string; sub: string }) {
  return (
    <div className="flex items-start gap-2.5">
      <span className="mt-0.5 text-primary">{icon}</span>
      <div>
        <div className="text-[12px] font-semibold">{title}</div>
        <div className="text-[11px] text-muted-foreground">{sub}</div>
      </div>
    </div>
  )
}
