import { cn } from "@/lib/utils"
import type { HTMLAttributes } from "react"

type Variant = "default" | "profit" | "loss" | "warn" | "muted" | "accent" | "info" | "solid-accent"

const variants: Record<Variant, string> = {
  default: "border-line-2 bg-bg-2 text-fg-dim",
  profit: "border-profit bg-profit/10 text-profit",
  loss: "border-loss bg-loss/10 text-loss",
  warn: "border-warn bg-warn/10 text-warn",
  muted: "border-line-2 bg-bg-2 text-muted-foreground",
  accent: "border-primary bg-primary/8 text-primary",
  info: "border-info bg-info/10 text-info",
  "solid-accent": "border-primary bg-primary text-background",
}

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: Variant
}

export function Badge({ variant = "default", className, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-[3px] border px-[7px] py-[2px] font-mono text-[10px] font-semibold uppercase leading-snug tracking-[0.06em] whitespace-nowrap",
        variants[variant],
        className,
      )}
      {...props}
    />
  )
}
