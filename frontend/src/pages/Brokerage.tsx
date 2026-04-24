import { useEffect, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useToast } from "@/contexts/toast-context"
import { PageHeader } from "@/components/layout/page-header"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Loader2, Link, Unlink, RefreshCw, ExternalLink } from "lucide-react"
import { cn } from "@/lib/utils"
import { api } from "@/lib/api"

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

  // Auto-select the account with the highest balance
  useEffect(() => {
    if (accounts.length > 0 && !selectedAccountId) {
      const richest = [...accounts].sort((a, b) => (b.balance ?? 0) - (a.balance ?? 0))[0]
      setSelectedAccountId(richest.id)
    }
  }, [accounts, selectedAccountId])

  // Handle SnapTrade OAuth redirect back to this page
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const statusCode = params.get("status_code")
    const status = params.get("status")
    const errorCode = params.get("error_code")

    if (!statusCode && !status) return

    // Clean up URL params immediately
    window.history.replaceState({}, "", window.location.pathname)

    if (status === "SUCCESS" || statusCode === "200") {
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
        description="Connect and sync your Wealthsimple account via SnapTrade"
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
          ) : (
            <Button
              variant="outline"
              size="sm"
              onClick={() => connectMutation.mutate()}
              disabled={connectMutation.isPending}
              className="border-primary/30 text-primary hover:bg-primary/10"
            >
              {connectMutation.isPending
                ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                : <ExternalLink className="mr-1.5 h-3.5 w-3.5" />}
              Connect Wealthsimple
            </Button>
          )
        }
      />

      <div
        className={cn(
          "rounded-xl border-2 p-5 transition-all",
          connected
            ? "border-emerald-500/30 bg-emerald-500/5"
            : "border-border/60 bg-card",
        )}
      >
        {/* Header row */}
        <div className="flex items-center gap-3 mb-4">
          <div className={cn(
            "flex items-center justify-center h-10 w-10 rounded-lg",
            connected ? "bg-emerald-500/15" : "bg-muted/60",
          )}>
            {connected
              ? <Link className="h-5 w-5 text-emerald-500" />
              : <Unlink className="h-5 w-5 text-muted-foreground" />}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <p className="font-semibold">Wealthsimple</p>
              <Badge variant={connected ? "profit" : "muted"} className="text-[10px]">
                {isLoading ? "..." : connected ? "CONNECTED" : "NOT CONNECTED"}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground mt-0.5">
              {connected
                ? `${accounts.length} account${accounts.length !== 1 ? "s" : ""} linked via SnapTrade`
                : "Connect your brokerage to auto-sync portfolio positions and cash"}
            </p>
          </div>
        </div>

        {/* Account list */}
        {connected && accounts.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
              Accounts — click to select for sync
            </p>
            {accounts.map((acc) => (
              <div
                key={acc.id}
                onClick={() => setSelectedAccountId(acc.id)}
                className={cn(
                  "flex items-center justify-between rounded-lg px-3 py-2.5 cursor-pointer transition-colors border",
                  selectedAccountId === acc.id
                    ? "bg-emerald-500/10 border-emerald-500/30"
                    : "hover:bg-muted/40 border-transparent",
                )}
              >
                <div className="flex items-center gap-2.5">
                  {selectedAccountId === acc.id && (
                    <span className="h-2 w-2 rounded-full bg-emerald-500 shrink-0" />
                  )}
                  {selectedAccountId !== acc.id && (
                    <span className="h-2 w-2 rounded-full bg-muted-foreground/30 shrink-0" />
                  )}
                  <span className={cn(
                    "text-sm font-medium",
                    selectedAccountId === acc.id ? "text-emerald-400" : "text-muted-foreground",
                  )}>
                    {acc.name} {acc.account_type ? `(${acc.account_type})` : ""}
                  </span>
                </div>
                {(acc.balance ?? 0) > 0 && (
                  <span className={cn(
                    "text-sm",
                    selectedAccountId === acc.id ? "text-emerald-400/80" : "text-muted-foreground",
                  )}>
                    {acc.currency} ${(acc.balance ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Empty state */}
        {!connected && !isLoading && (
          <div className="text-center py-8">
            <p className="text-sm text-muted-foreground">
              Click "Connect Wealthsimple" above to link your account via SnapTrade.
            </p>
            <p className="text-xs text-muted-foreground/60 mt-1">
              Your credentials are handled securely by SnapTrade — we never see your password.
            </p>
          </div>
        )}
      </div>
    </>
  )
}
