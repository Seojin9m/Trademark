import { cn } from "@/lib/utils"
import type { HTMLAttributes } from "react"

type Variant = "default" | "profit" | "loss" | "warn" | "muted"

const variants: Record<Variant, string> = {
  default: "bg-primary/15 text-primary border-primary/20",
  profit: "bg-profit/10 text-profit border-profit/20",
  loss: "bg-loss/10 text-loss border-loss/20",
  warn: "bg-warn/10 text-warn border-warn/20",
  muted: "bg-muted text-muted-foreground border-border",
}

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: Variant
}

export function Badge({ variant = "default", className, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide",
        variants[variant],
        className,
      )}
      {...props}
    />
  )
}
