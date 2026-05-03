import type { ReactNode } from "react"

interface PageHeaderProps {
  title: ReactNode
  description?: string
  actions?: ReactNode
}

export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <div className="mb-5 flex items-start justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2.5">{title}</h1>
        {description && (
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}
