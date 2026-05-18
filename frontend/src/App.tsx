import { useState } from "react"
import { Routes, Route, Outlet, useLocation } from "react-router-dom"
import { Sidebar } from "@/components/layout/sidebar"
import { Topbar } from "@/components/layout/topbar"
import { ChatWidget } from "@/components/chat/ChatWidget"
import { AuthFlow } from "@/components/auth/AuthFlow"
import { useAuth } from "@/contexts/auth-context"
import { cn } from "@/lib/utils"
import BrokerageCallback from "@/pages/BrokerageCallback"
import Rankings from "@/pages/Rankings"
import PortfolioOverview from "@/pages/PortfolioOverview"
import SignalDashboard from "@/pages/SignalDashboard"
import PendingTrades from "@/pages/PendingTrades"
import DecisionLog from "@/pages/DecisionLog"
import RiskMonitor from "@/pages/RiskMonitor"
import BacktestResults from "@/pages/BacktestResults"
import PipelineControl from "@/pages/PipelineControl"
import NewsResearch from "@/pages/NewsResearch"
import LearningDashboard from "@/pages/LearningDashboard"
import Brokerage from "@/pages/Brokerage"
import AnalystReview from "@/pages/AnalystReview"
import StockDataGrid from "@/pages/StockDataGrid"
import Watchlist from "@/pages/Watchlist"

function Layout() {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
      <main
        className={cn(
          "flex-1 min-w-0 transition-[margin-left] duration-200",
          collapsed ? "ml-14" : "ml-[220px]",
        )}
      >
        <Topbar />
        <div className="mx-auto max-w-[1480px] px-7 py-[22px] pb-20 animate-fade-in">
          <Outlet />
        </div>
      </main>
      <ChatWidget />
    </div>
  )
}

export default function App() {
  const { user, brokerageConnected, loading } = useAuth()
  const { pathname } = useLocation()

  // SnapTrade's OAuth popup lands at /brokerage/callback. It must short-circuit
  // BEFORE the auth gate, otherwise the popup re-renders the AuthFlow brokerage
  // step (the popup has the same localStorage session but no brokerage yet) and
  // the user appears stuck in an infinite "connect" loop. The callback page
  // just calls window.close() and the parent window picks up the connection.
  if (pathname === "/brokerage/callback") {
    return <BrokerageCallback />
  }

  // While auth state hydrates from localStorage, render nothing rather than
  // flashing the login screen. The AuthProvider's `loading` flips once
  // getSession() resolves.
  if (loading) return null

  // Anyone who hasn't signed up OR hasn't connected a brokerage yet stays on
  // the AuthFlow. We rely on the user_metadata.has_brokerage flag rather than
  // an extra round-trip to /api/brokerage/status.
  if (!user || !brokerageConnected) {
    return <AuthFlow onComplete={() => { /* hooks/state will re-render */ }} />
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Rankings />} />
        <Route path="portfolio" element={<PortfolioOverview />} />
        <Route path="signals" element={<SignalDashboard />} />
        <Route path="trades" element={<PendingTrades />} />
        <Route path="decisions" element={<DecisionLog />} />
        <Route path="risk" element={<RiskMonitor />} />
        <Route path="research" element={<NewsResearch />} />
        <Route path="backtest" element={<BacktestResults />} />
        <Route path="learning" element={<LearningDashboard />} />
        <Route path="pipeline" element={<PipelineControl />} />
        <Route path="brokerage" element={<Brokerage />} />
        <Route path="analyst" element={<AnalystReview />} />
        <Route path="data" element={<StockDataGrid />} />
        <Route path="watchlist" element={<Watchlist />} />
      </Route>
    </Routes>
  )
}
