import { useEffect, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useToast } from "@/contexts/toast-context"
import { PageHeader } from "@/components/layout/page-header"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardTitle } from "@/components/ui/card"
import { SectionTitle } from "@/components/ui/section-title"
import { Loader2, Unlink, RefreshCw, ExternalLink, Building2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { api } from "@/lib/api"

const COMING_SOON_BROKERS = [
  { name: "Questrade", tag: "CA" },
  { name: "Interactive Brokers", tag: "IBKR" },
  { name: "TD Direct Investing", tag: "CA" },
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

  // Aggregate balance across all linked accounts (within their native currencies — we don't FX-convert here)
  const totalBalance = accounts.reduce((sum, a) => sum + (a.balance ?? 0), 0)
  const totalCurrency = accounts[0]?.currency || "USD"

  // Last sync from any account
  const lastSync = accounts
    .map((a) => a.last_sync)
    .filter((d): d is string => !!d)
    .sort()
    .pop()
  const lastSyncDisplay = lastSync ? new Date(lastSync).toLocaleString("en-US", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).replace(",", " ·") : null

  return (
    <>
      <PageHeader
        title="Brokerage"
        description="Connect a brokerage to enable real-money portfolio sync and execution"
        actions={
          connected ? (
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="primary"
                onClick={() => syncMutation.mutate()}
                disabled={syncMutation.isPending || !selectedAccountId}
              >
                {syncMutation.isPending
                  ? <Loader2 className="h-3 w-3 animate-spin" />
                  : <RefreshCw className="h-3 w-3" />}
                Sync Portfolio
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => disconnectMutation.mutate()}
                disabled={disconnectMutation.isPending}
              >
                <Unlink className="h-3 w-3" />
                Disconnect
              </Button>
            </div>
          ) : undefined
        }
      />

      <div className="flex flex-col gap-[14px]">
        {/* Wealthsimple card — flush layout */}
        <Card className={cn(connected && "border-profit/30 bg-profit/[0.03]")}>
          <div className="flex items-center gap-[18px] px-[22px] py-[18px]">
            <img
              src="/brokerages/wealthsimple_logo.jpg"
              alt="Wealthsimple"
              className="h-16 w-16 rounded-lg object-cover border border-line shrink-0"
            />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2.5 mb-1.5">
                <span className="text-[17px] font-semibold text-foreground">Wealthsimple</span>
                <Badge variant={connected ? "profit" : "muted"}>
                  <span className={cn(
                    "h-[6px] w-[6px] rounded-full",
                    connected ? "bg-profit" : "bg-muted-foreground",
                  )} />
                  {isLoading ? "..." : connected ? "CONNECTED" : "NOT CONNECTED"}
                </Badge>
              </div>
              <div className="text-[12.5px] text-muted-foreground">
                {connected
                  ? `${accounts.length} account${accounts.length === 1 ? "" : "s"} available · linked via SnapTrade${lastSyncDisplay ? ` · last sync ${lastSyncDisplay}` : ""}`
                  : "Auto-sync portfolio positions and cash balance"}
              </div>
            </div>
            {!connected ? (
              <Button
                size="lg"
                variant="primary"
                onClick={() => connectMutation.mutate()}
                disabled={connectMutation.isPending}
              >
                {connectMutation.isPending
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : <ExternalLink className="h-4 w-4" />}
                Connect
              </Button>
            ) : totalBalance > 0 ? (
              <div className="text-right shrink-0">
                <div className="font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-0.5">
                  Total balance
                </div>
                <div className="font-mono text-[18px] font-medium text-foreground tabular-nums">
                  {totalCurrency} ${totalBalance.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
              </div>
            ) : null}
          </div>

          {!connected && !isLoading && (
            <div className="px-[22px] pb-[18px]">
              <div className="rounded-[4px] border border-line bg-bg-2 px-4 py-3 text-center">
                <p className="text-[12.5px] text-muted-foreground">
                  Click "Connect" to link your Wealthsimple account via SnapTrade
                </p>
                <p className="text-[11px] text-muted-2 mt-0.5">
                  Your credentials are handled securely by SnapTrade — we never see your password
                </p>
              </div>
            </div>
          )}
        </Card>

        {/* Account selector */}
        {connected && accounts.length > 0 && (
          <Card>
            <CardTitle meta="Choose which account to sync">Account Selector</CardTitle>
            <div className="flex flex-col gap-1.5 p-4">
              {accounts.map((acc) => {
                const selected = selectedAccountId === acc.id
                const last4 = acc.number ? `····${acc.number.slice(-4)}` : `····${acc.id.slice(-4)}`
                return (
                  <label
                    key={acc.id}
                    className={cn(
                      "flex items-center gap-[14px] px-[14px] py-3 rounded-[4px] border cursor-pointer transition-colors",
                      selected
                        ? "bg-primary/[0.08] border-primary"
                        : "bg-bg-2 border-line hover:border-line-2",
                    )}
                  >
                    <input
                      type="radio"
                      name="account"
                      checked={selected}
                      onChange={() => setSelectedAccountId(acc.id)}
                      className="accent-primary h-[14px] w-[14px]"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-[13.5px] font-semibold text-foreground">
                        {acc.name}
                      </div>
                      <div className="font-mono text-[11px] text-muted-2">
                        {acc.account_type ? `${acc.account_type} · ` : ""}{last4}
                      </div>
                    </div>
                    {(acc.balance ?? 0) > 0 && (
                      <div className="font-mono text-[14px] font-semibold tabular-nums text-foreground">
                        {acc.currency} ${(acc.balance ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </div>
                    )}
                  </label>
                )
              })}
            </div>
          </Card>
        )}

        {/* Coming soon */}
        <div>
          <SectionTitle>Coming Soon</SectionTitle>
          <div className="grid grid-cols-3 gap-3">
            {COMING_SOON_BROKERS.map((broker) => (
              <div
                key={broker.name}
                className="rounded-md border border-line bg-surface px-5 py-4 opacity-55"
              >
                <div className="flex items-center gap-[14px]">
                  <div className="flex items-center justify-center h-9 w-9 rounded-[4px] bg-bg-2 border border-dashed border-line-2 shrink-0">
                    <Building2 className="h-[18px] w-[18px] text-muted-2" />
                  </div>
                  <span className="text-[13.5px] font-semibold text-foreground">
                    {broker.name}
                  </span>
                  <span className="flex-1" />
                  <Badge variant="muted">{broker.tag}</Badge>
                </div>
                <div className="mt-2.5 font-mono text-[10.5px] uppercase tracking-[0.08em] text-muted-2">
                  Coming soon
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
