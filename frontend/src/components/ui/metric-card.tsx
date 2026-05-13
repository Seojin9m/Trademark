import { cn } from "@/lib/utils"

interface MetricCardProps {
  label: string
  value: string
  valueNode?: React.ReactNode
  delta?: string
  deltaValue?: number
  sub?: string
  accent?: boolean
  sparkline?: React.ReactNode
  className?: string
}

export function MetricCard({ label, value, valueNode, delta, deltaValue, sub, accent, sparkline, className }: MetricCardProps) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-md border bg-surface p-[14px_16px]",
        accent ? "border-primary shadow-[inset_0_0_0_1px_rgba(197,251,69,0.08)]" : "border-line",
        className,
      )}
    >
      <div className="flex items-center gap-1.5 font-mono text-[9.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </div>
      <div className="mt-1.5 flex items-end justify-between gap-3">
        <div className="font-mono text-[22px] font-medium tracking-[-0.01em] tabular-nums text-foreground">
          {valueNode ?? value}
        </div>
        {sparkline && <div className="shrink-0 opacity-90">{sparkline}</div>}
      </div>
      {(delta || sub) && (
        <div className="mt-1 flex items-center gap-1 font-mono text-[11px] tabular-nums">
          {delta && (
            <span
              className={cn(
                deltaValue !== undefined && deltaValue > 0 && "text-profit",
                deltaValue !== undefined && deltaValue < 0 && "text-loss",
                deltaValue === undefined && "text-muted-foreground",
              )}
            >
              {deltaValue !== undefined && deltaValue > 0 && "▲ "}
              {deltaValue !== undefined && deltaValue < 0 && "▼ "}
              {delta}
            </span>
          )}
          {sub && <span className="text-muted-foreground">{sub}</span>}
        </div>
      )}
    </div>
  )
}
