import { NavLink } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { cn } from "@/lib/utils"
import { usePipeline } from "@/contexts/pipeline-context"
import { useAnalyst } from "@/contexts/analyst-context"
import { api } from "@/lib/api"
import type { Proposal } from "@/lib/api"
import {
  LayoutDashboard,
  BarChart3,
  ArrowLeftRight,
  ClipboardList,
  ShieldAlert,
  FlaskConical,
  Workflow,
  Newspaper,
  Brain,
  Wallet,
  BrainCircuit,
  Database,
} from "lucide-react"

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Portfolio" },
  { to: "/analyst", icon: BrainCircuit, label: "Analyst" },
  { to: "/signals", icon: BarChart3, label: "Signals" },
  { to: "/trades", icon: ArrowLeftRight, label: "Trades" },
  { to: "/decisions", icon: ClipboardList, label: "Decisions" },
  { to: "/risk", icon: ShieldAlert, label: "Risk" },
  { to: "/data", icon: Database, label: "Data Grid" },
  { to: "/research", icon: Newspaper, label: "Research" },
  { to: "/learning", icon: Brain, label: "Learning" },
  { to: "/backtest", icon: FlaskConical, label: "Backtest" },
  { to: "/brokerage", icon: Wallet, label: "Brokerage" },
  { to: "/pipeline", icon: Workflow, label: "Pipeline" },
]

export function Sidebar() {
  const { running } = usePipeline()
  const { analyzing } = useAnalyst()

  const { data: proposals } = useQuery<Proposal[]>({
    queryKey: ["proposals"],
    queryFn: () => api.getProposals(undefined, 100),
    staleTime: 30_000,
  })
  const pendingCount = (proposals ?? []).filter(
    (p) => ["PENDING", "NEEDS_REVIEW", "JUDGE_APPROVED"].includes(p.status),
  ).length

  return (
    <aside className="fixed inset-y-0 left-0 z-50 flex w-60 flex-col border-r border-border/60 bg-card/80 backdrop-blur-xl">
      <div className="flex h-16 items-center gap-2 border-b border-border/60 px-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/15">
          <span className="text-sm font-semibold text-primary">$</span>
        </div>
        <span className="text-base font-semibold tracking-tight">Trademark</span>
      </div>

      <nav className="flex-1 space-y-1 px-3 pt-4">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-150",
                isActive
                  ? "bg-primary/10 text-primary shadow-sm shadow-primary/5"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground",
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span>{label}</span>
            {to === "/trades" && pendingCount > 0 && (
              <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-amber-500/20 text-amber-400 text-[10px] font-semibold px-1.5">
                {pendingCount}
              </span>
            )}
            {to === "/analyst" && analyzing && (
              <span className="ml-auto h-2 w-2 rounded-full bg-primary animate-pulse-dot" />
            )}
            {to === "/pipeline" && running && (
              <span className="ml-auto h-2 w-2 rounded-full bg-primary animate-pulse-dot" />
            )}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-border/60 px-5 py-4">
        <p className="text-[11px] font-medium text-muted-foreground/60">
          v4.0 &middot; Phase 8
        </p>
      </div>
    </aside>
  )
}
