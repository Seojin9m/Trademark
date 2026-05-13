import type { ReactNode } from "react"

interface PageHeaderProps {
  title: ReactNode
  description?: string
  actions?: ReactNode
  prefix?: ReactNode
}

export function PageHeader({ title, description, actions, prefix }: PageHeaderProps) {
  return (
    <div className="mb-[18px] flex items-start justify-between gap-6 border-b border-line pb-[18px]">
      <div>
        <h1 className="flex items-center gap-3 text-[22px] font-semibold tracking-[-0.02em]">
          {prefix}
          {title}
        </h1>
        {description && (
          <p className="mt-1.5 text-[12.5px] text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
