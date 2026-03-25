import { cn } from "@/lib/utils"
import type { ButtonHTMLAttributes } from "react"

type Variant = "default" | "outline" | "ghost" | "destructive" | "secondary"
type Size = "sm" | "md" | "lg" | "icon"

const variantStyles: Record<Variant, string> = {
  default:
    "bg-primary text-primary-foreground shadow-md shadow-primary/20 hover:bg-primary/90 active:shadow-none",
  outline:
    "border border-border bg-transparent hover:bg-accent hover:border-border/80",
  ghost: "hover:bg-accent",
  destructive:
    "bg-destructive text-white shadow-md shadow-destructive/20 hover:bg-destructive/90",
  secondary:
    "bg-secondary text-secondary-foreground border border-border hover:bg-secondary/80",
}

const sizeStyles: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-9 px-4 text-sm gap-2",
  lg: "h-11 px-6 text-sm gap-2",
  icon: "h-9 w-9",
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
        "inline-flex items-center justify-center rounded-lg font-medium transition-all duration-150",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "disabled:pointer-events-none disabled:opacity-50",
        variantStyles[variant],
        sizeStyles[size],
        className,
      )}
      {...props}
    />
  )
}
