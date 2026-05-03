import { useEffect, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useToast } from "@/contexts/toast-context"
import { PageHeader } from "@/components/layout/page-header"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Loader2, Unlink, RefreshCw, ExternalLink, Building2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { api } from "@/lib/api"

const COMING_SOON_BROKERS = [
  { name: "Questrade", icon: "Q" },
  { name: "Interactive Brokers", icon: "IB" },
  { name: "TD Direct Investing", icon: "TD" },
]

export default function Brokerage() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const [selectedAccountId, setSelectedAccountId] = useState<string>("")

  const { data: status, isLoading } = useQuery({
    queryKey: ["brokerage-status"],
    queryFn: api.getBrokerageStatus,
    refetchInterval: 10000,
  })

  const connectMutation = useMutation({
    mutationFn: () => api.connectBrokerage(),
    onSuccess: (data) => {
      window.open(data.url, "_blank")
      toast("info", "Connection Portal Opened", "Complete the login in the new tab, then click Sync")
    },
    onError: (e) => toast("error", "Connection Failed", String(e)),
  })

  const syncMutation = useMutation({
    mutationFn: () => api.syncPortfolio(selectedAccountId || undefined),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["portfolio"] })
      queryClient.invalidateQueries({ queryKey: ["brokerage-status"] })
      toast("success", "Portfolio Synced", `${data.positions} positions, ${data.currency} $${data.cash.toFixed(2)} cash`)
    },
    onError: (e: Error) => toast("error", "Sync Failed", e.message.replace(/^Error:\s*/, "")),
  })

  const disconnectMutation = useMutation({
    mutationFn: api.disconnectBrokerage,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["brokerage-status"] })
      setSelectedAccountId("")
      toast("success", "Disconnected", "Brokerage connection removed")
    },
  })

  const connected = status?.connected ?? false
  const accounts = status?.accounts ?? []

  useEffect(() => {
    if (accounts.length > 0 && !selectedAccountId) {
      const richest = [...accounts].sort((a, b) => (b.balance ?? 0) - (a.balance ?? 0))[0]
      setSelectedAccountId(richest.id)
    }
  }, [accounts, selectedAccountId])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const statusCode = params.get("status_code")
    const statusParam = params.get("status")
    const errorCode = params.get("error_code")

    if (!statusCode && !statusParam) return

    window.history.replaceState({}, "", window.location.pathname)

    if (statusParam === "SUCCESS" || statusCode === "200") {
      toast("info", "Brokerage Connected!", "Syncing your portfolio...")
      api.syncPortfolio().then((data) => {
        queryClient.invalidateQueries({ queryKey: ["portfolio"] })
        queryClient.invalidateQueries({ queryKey: ["brokerage-status"] })
        toast("success", "Portfolio Synced", `${data.positions} positions, ${data.currency} $${data.cash.toFixed(2)} cash`)
      }).catch((e) => {
        toast("error", "Sync Failed", String(e))
      })
    } else {
      const msg = errorCode === "1066"
        ? "Wealthsimple is not enabled on your SnapTrade partner account. Contact SnapTrade support to enable WEALTHSIMPLETRADE for your Client ID."
        : `Connection error (code ${errorCode ?? statusCode})`
      toast("error", "Brokerage Connection Failed", msg)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <PageHeader
        title="Brokerage"
        actions={
          connected ? (
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => syncMutation.mutate()}
                disabled={syncMutation.isPending || !selectedAccountId}
                className="border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10"
              >
                {syncMutation.isPending
                  ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
                Sync Portfolio
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => disconnectMutation.mutate()}
                disabled={disconnectMutation.isPending}
                className="border-red-500/30 text-red-400 hover:bg-red-500/10"
              >
                <Unlink className="mr-1.5 h-3.5 w-3.5" />
                Disconnect
              </Button>
            </div>
          ) : undefined
        }
      />

      <div className="space-y-4">
        {/* Wealthsimple card */}
        <Card className={cn(
          "border-2 transition-all",
          connected ? "border-emerald-500/30 bg-emerald-500/[0.03]" : "border-border/60",
        )}>
          <CardContent>
            <div className="flex items-center gap-4 mb-5">
              <img
                src="/brokerages/wealthsimple_logo.jpg"
                alt="Wealthsimple"
                className="h-12 w-12 rounded-xl object-cover border border-border/40"
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2.5">
                  <p className="text-lg font-semibold">Wealthsimple</p>
                  <Badge variant={connected ? "profit" : "muted"} className="text-[10px]">
                    {isLoading ? "..." : connected ? "CONNECTED" : "NOT CONNECTED"}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {connected
                    ? `${accounts.length} account${accounts.length !== 1 ? "s" : ""} linked via SnapTrade`
                    : "Auto-sync portfolio positions and cash balance"}
                </p>
              </div>
              {!connected && (
                <Button
                  onClick={() => connectMutation.mutate()}
                  disabled={connectMutation.isPending}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white border-emerald-600 shrink-0"
                >
                  {connectMutation.isPending
                    ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                    : <ExternalLink className="mr-1.5 h-4 w-4" />}
                  Connect
                </Button>
              )}
            </div>

            {/* Account list */}
            {connected && accounts.length > 0 && (
              <div>
                <p className="text-[10.5px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                  Select account for sync
                </p>
                <div className="space-y-1">
                  {accounts.map((acc) => {
                    const selected = selectedAccountId === acc.id
                    return (
                      <button
                        key={acc.id}
                        onClick={() => setSelectedAccountId(acc.id)}
                        className={cn(
                          "w-full flex items-center justify-between rounded-lg px-3.5 py-3 transition-all border text-left",
                          selected
                            ? "bg-emerald-500/10 border-emerald-500/30"
                            : "hover:bg-muted/30 border-transparent",
                        )}
                      >
                        <div className="flex items-center gap-3">
                          <div className={cn(
                            "h-2 w-2 rounded-full shrink-0 transition-colors",
                            selected ? "bg-emerald-500" : "bg-muted-foreground/30",
                          )} />
                          <div>
                            <span className={cn(
                              "text-sm font-medium block",
                              selected ? "text-emerald-400" : "text-foreground/80",
                            )}>
                              {acc.name}
                            </span>
                            {acc.account_type && (
                              <span className="text-[11px] text-muted-foreground/60">
                                {acc.account_type}
                              </span>
                            )}
                          </div>
                        </div>
                        {(acc.balance ?? 0) > 0 && (
                          <span className={cn(
                            "text-sm font-medium tabular-nums",
                            selected ? "text-emerald-400/80" : "text-muted-foreground/60",
                          )}>
                            {acc.currency} ${(acc.balance ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </span>
                        )}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Empty state */}
            {!connected && !isLoading && (
              <div className="rounded-lg border border-border/40 bg-muted/10 px-4 py-5 text-center">
                <p className="text-sm text-muted-foreground">
                  Click "Connect" to link your Wealthsimple account via SnapTrade
                </p>
                <p className="text-[11px] text-muted-foreground/50 mt-1">
                  Your credentials are handled securely by SnapTrade — we never see your password
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Coming soon */}
        <div>
          <p className="text-[10.5px] font-semibold text-muted-foreground uppercase tracking-wider mb-3 px-1">
            More brokerages coming soon
          </p>
          <div className="grid grid-cols-3 gap-3">
            {COMING_SOON_BROKERS.map((broker) => (
              <div
                key={broker.name}
                className="rounded-xl border border-dashed border-border/40 bg-card/30 px-4 py-4 flex items-center gap-3 opacity-50"
              >
                <div className="flex items-center justify-center h-10 w-10 rounded-lg bg-muted/40 shrink-0">
                  <Building2 className="h-5 w-5 text-muted-foreground/50" />
                </div>
                <div>
                  <p className="text-sm font-medium text-muted-foreground/70">{broker.name}</p>
                  <p className="text-[11px] text-muted-foreground/40">Coming soon</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
