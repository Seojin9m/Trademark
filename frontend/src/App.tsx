import { useState } from "react"
import { Routes, Route, Outlet } from "react-router-dom"
import { Sidebar } from "@/components/layout/sidebar"
import { Topbar } from "@/components/layout/topbar"
import { ChatWidget } from "@/components/chat/ChatWidget"
import { cn } from "@/lib/utils"
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
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<PortfolioOverview />} />
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
      </Route>
    </Routes>
  )
}
