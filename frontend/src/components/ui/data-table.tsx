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
      <p className="py-12 text-center text-sm text-muted-foreground">{emptyMessage}</p>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/60">
            {columns.map((col) => (
              <th
                key={col.key}
                className={cn(
                  "pb-3 px-3 first:pl-0 last:pr-0 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground",
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
              className="border-b border-border/30 transition-colors hover:bg-accent/30"
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={cn(
                    compact ? "py-1.5 px-3 first:pl-0 last:pr-0" : "py-2.5 px-3 first:pl-0 last:pr-0",
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
