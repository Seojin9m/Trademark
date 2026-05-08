import { cn } from "@/lib/utils"
import type { ReactNode } from "react"

export interface Column<T> {
  key: string
  header: string
  align?: "left" | "right" | "center"
  className?: string
  render: (row: T) => ReactNode
}

interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  rowKey: (row: T) => string
  emptyMessage?: string
  compact?: boolean
}

export function DataTable<T>({ columns, data, rowKey, emptyMessage = "No data", compact }: DataTableProps<T>) {
  if (data.length === 0) {
    return (
      <p className="py-12 text-center font-mono text-[12px] text-muted-foreground">{emptyMessage}</p>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full font-mono text-[12px] tabular-nums">
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={cn(
                  "sticky top-0 z-[1] border-b border-line bg-bg-2 px-3 py-2.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground",
                  col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : "text-left",
                  col.className,
                )}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr
              key={rowKey(row)}
              className="border-b border-line transition-colors hover:bg-surface-2"
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={cn(
                    compact ? "px-3 py-1.5" : "px-3 py-[9px]",
                    "text-fg-dim",
                    col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : "text-left",
                    col.className,
                  )}
                >
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
