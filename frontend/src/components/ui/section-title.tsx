import type { ReactNode } from "react"

interface SectionTitleProps {
  children: ReactNode
  meta?: ReactNode
}

export function SectionTitle({ children, meta }: SectionTitleProps) {
  return (
    <h3 className="flex items-center gap-3 my-3 font-mono text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
      <span>{children}</span>
      <span className="flex-1 h-px bg-line" />
      {meta && (
        <span className="text-muted-2 font-medium tracking-[0.04em]">{meta}</span>
      )}
    </h3>
  )
}
