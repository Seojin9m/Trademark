import { cn, pnlColor } from "@/lib/utils"
import { TrendingUp, TrendingDown, Minus } from "lucide-react"

interface MetricCardProps {
  label: string
  value: string
  delta?: string
  deltaValue?: number
  className?: string
}

export function MetricCard({ label, value, delta, deltaValue, className }: MetricCardProps) {
  const TrendIcon =
    deltaValue && deltaValue > 0
      ? TrendingUp
      : deltaValue && deltaValue < 0
        ? TrendingDown
        : Minus

  return (
    <div
      className={cn(
        "group relative overflow-hidden rounded-xl border border-border/60 bg-card p-5 shadow-sm shadow-black/20 transition-colors hover:border-border",
        className,
      )}
    >
      <div className="absolute inset-0 bg-gradient-to-br from-primary/[0.03] to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
      <p className="relative text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="relative mt-2 text-2xl font-medium tracking-tight">{value}</p>
      {delta && (
        <div className="relative mt-2 flex items-center gap-1.5">
          {deltaValue !== undefined && (
            <TrendIcon className={cn("h-3.5 w-3.5", pnlColor(deltaValue))} />
          )}
          <span
            className={cn(
              "text-xs font-medium",
              deltaValue !== undefined ? pnlColor(deltaValue) : "text-muted-foreground",
            )}
          >
            {delta}
          </span>
        </div>
      )}
    </div>
  )
}
