import { cn } from "@/lib/utils"
import type { HTMLAttributes, ReactNode } from "react"

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-md border border-line bg-surface",
        className,
      )}
      {...props}
    />
  )
}

export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col space-y-1.5 px-4 pt-4", className)} {...props} />
}

interface CardTitleProps extends HTMLAttributes<HTMLDivElement> {
  meta?: ReactNode
  action?: ReactNode
}

export function CardTitle({ className, meta, action, children, ...props }: CardTitleProps) {
  return (
    <div
      className={cn(
        "flex items-center justify-between border-b border-line px-4 py-3",
        className,
      )}
      {...props}
    >
      <div className="flex items-center gap-2.5">
        <span className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
          {children}
        </span>
        {meta && (
          <span className="font-mono text-[10.5px] tracking-[0.04em] text-muted-2">
            {meta}
          </span>
        )}
      </div>
      {action}
    </div>
  )
}

export function CardContent({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4", className)} {...props} />
}
