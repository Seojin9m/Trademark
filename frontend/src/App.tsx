import { Routes, Route, Outlet } from "react-router-dom"
import { Sidebar } from "@/components/layout/sidebar"
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

function Layout() {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <main className="ml-60 flex-1 px-6 py-5">
        <div className="mx-auto max-w-[1400px] animate-fade-in">
          <Outlet />
        </div>
      </main>
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
      </Route>
    </Routes>
  )
}
