import { cn } from "@/lib/utils"
import type { ButtonHTMLAttributes } from "react"

type Variant = "default" | "outline" | "ghost" | "destructive" | "secondary" | "primary"
type Size = "sm" | "md" | "lg" | "icon"

const variantStyles: Record<Variant, string> = {
  default:
    "border border-line-2 bg-surface text-foreground hover:bg-surface-2 hover:border-muted-2",
  primary:
    "bg-primary text-background border border-primary font-semibold hover:bg-accent-dim hover:border-accent-dim",
  outline:
    "border border-line-2 bg-transparent hover:bg-surface hover:border-muted-2",
  ghost:
    "bg-transparent border border-transparent text-muted-foreground hover:bg-surface hover:text-foreground",
  destructive:
    "border border-line-2 text-loss hover:bg-loss/10 hover:border-loss",
  secondary:
    "border border-line-2 bg-surface-2 text-foreground hover:bg-surface hover:border-muted-2",
}

const sizeStyles: Record<Size, string> = {
  sm: "h-[24px] px-2 text-[11px] gap-1.5",
  md: "h-[30px] px-3 text-[12px] gap-1.5",
  lg: "h-9 px-4 text-[13px] gap-2",
  icon: "h-[30px] w-[30px]",
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
}

export function Button({
  variant = "default",
  size = "md",
  className,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-[4px] font-medium transition-all duration-150 whitespace-nowrap",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
        "disabled:pointer-events-none disabled:opacity-50",
        variantStyles[variant],
        sizeStyles[size],
        className,
      )}
      {...props}
    />
  )
}
