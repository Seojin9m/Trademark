import { NavLink } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { cn } from "@/lib/utils"
import { usePipeline } from "@/contexts/pipeline-context"
import { useAnalyst } from "@/contexts/analyst-context"
import { api } from "@/lib/api"
import type { Proposal } from "@/lib/api"
import { TrademarkLogo } from "./trademark-logo"
import {
  LayoutDashboard,
  BarChart3,
  ArrowLeftRight,
  // ClipboardList,  // unused: Decisions tab hidden
  // ShieldAlert,    // unused: Risk tab hidden
  // FlaskConical,   // unused: Backtest tab hidden
  Workflow,
  Newspaper,
  Brain,
  Wallet,
  BrainCircuit,
  Database,
  Star,
  PanelLeft,
} from "lucide-react"

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Portfolio" },
  { to: "/analyst", icon: BrainCircuit, label: "Analyst" },
  { to: "/signals", icon: BarChart3, label: "Signals" },
  { to: "/trades", icon: ArrowLeftRight, label: "Trades" },
  // { to: "/decisions", icon: ClipboardList, label: "Decisions" },  // hidden
  // { to: "/risk", icon: ShieldAlert, label: "Risk" },              // hidden
  { to: "/data", icon: Database, label: "Data Grid" },
  // { to: "/research", icon: Newspaper, label: "Research" },        // hidden
  { to: "/watchlist", icon: Star, label: "Watchlist" },
  // { to: "/learning", icon: Brain, label: "Learning" },            // hidden
  // { to: "/backtest", icon: FlaskConical, label: "Backtest" },     // hidden
  { to: "/brokerage", icon: Wallet, label: "Brokerage" },
  { to: "/pipeline", icon: Workflow, label: "Pipeline" },
]

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
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
    <aside
      className={cn(
        "fixed inset-y-0 left-0 z-50 flex flex-col border-r border-line bg-bg-2 transition-[width] duration-200",
        collapsed ? "w-14" : "w-[220px]",
      )}
    >
      {/* Header */}
      <div className={cn(
        "flex h-14 items-center border-b border-line shrink-0",
        collapsed ? "justify-center px-0" : "gap-2.5 px-4",
      )}>
        <TrademarkLogo size={22} showWord={!collapsed} />
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-2.5">
        {!collapsed && (
          <div className="px-2.5 pb-1.5 pt-2 font-mono text-[9.5px] font-medium uppercase tracking-[0.12em] text-muted-2">
            Workspace
          </div>
        )}
        <div className="flex flex-col gap-px">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                cn(
                  "relative flex items-center rounded-[4px] text-[12.5px] font-medium transition-colors duration-150",
                  collapsed
                    ? "h-9 w-9 mx-auto justify-center"
                    : "gap-2.5 px-2.5 py-[7px]",
                  isActive
                    ? "bg-primary/8 text-primary"
                    : "text-fg-dim hover:bg-surface hover:text-foreground",
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && !collapsed && (
                    <span className="absolute -left-2 top-1.5 bottom-1.5 w-0.5 rounded-full bg-primary" />
                  )}
                  <Icon className="h-[15px] w-[15px] shrink-0" strokeWidth={1.6} />
                  {!collapsed && (
                    <>
                      <span className="flex-1">{label}</span>
                      {to === "/trades" && pendingCount > 0 && (
                        <span className="flex h-[18px] min-w-[18px] items-center justify-center rounded-[3px] bg-primary px-[5px] font-mono text-[10px] font-semibold text-background">
                          {pendingCount}
                        </span>
                      )}
                      {to === "/analyst" && analyzing && (
                        <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse-ring" />
                      )}
                      {to === "/pipeline" && running && (
                        <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse-ring" />
                      )}
                    </>
                  )}
                  {collapsed && to === "/trades" && pendingCount > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-[3px] bg-primary px-1 font-mono text-[8px] font-bold text-background">
                      {pendingCount}
                    </span>
                  )}
                  {collapsed && to === "/pipeline" && running && (
                    <span className="absolute top-0.5 right-0.5 h-1.5 w-1.5 rounded-full bg-primary animate-pulse-ring" />
                  )}
                  {collapsed && to === "/analyst" && analyzing && (
                    <span className="absolute top-0.5 right-0.5 h-1.5 w-1.5 rounded-full bg-primary animate-pulse-ring" />
                  )}
                </>
              )}
            </NavLink>
          ))}
        </div>
      </nav>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-line px-4 py-3 shrink-0">
        {!collapsed && (
          <span className="font-mono text-[10px] tracking-[0.04em] text-muted-2">
            v4.0 · PHASE 8
          </span>
        )}
        <button
          onClick={onToggle}
          className={cn(
            "flex h-[22px] w-[22px] items-center justify-center rounded-[3px] text-muted-foreground transition-colors hover:bg-surface hover:text-foreground",
            collapsed && "mx-auto",
          )}
          title="Toggle sidebar"
        >
          <PanelLeft className="h-3.5 w-3.5" />
        </button>
      </div>
    </aside>
  )
}
