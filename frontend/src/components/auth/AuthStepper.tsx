import { Check } from "lucide-react"
import { cn } from "@/lib/utils"

interface Props {
  current: number // 0-indexed step currently being completed
  mode: "login" | "signup"
}

/**
 * Progress indicator above the signup form. Login is two steps so we hide
 * the stepper entirely (the form is short enough to feel single-page).
 */
export function AuthStepper({ current, mode }: Props) {
  if (mode !== "signup") return null

  const steps = ["Account", "Verify email", "Connect brokerage"]

  return (
    <div className="mb-6 flex items-center gap-2">
      {steps.map((label, i) => {
        const done = i < current
        const active = i === current
        return (
          <div key={label} className="flex items-center gap-2">
            <div
              className={cn(
                "flex items-center gap-2 rounded-full border px-2 py-1 font-mono text-[10px] uppercase tracking-[0.1em]",
                done && "border-primary/50 bg-primary/10 text-primary",
                active && "border-primary bg-primary/15 text-primary",
                !done && !active && "border-line-2 bg-bg-2 text-muted-2",
              )}
            >
              <span
                className={cn(
                  "flex h-4 w-4 items-center justify-center rounded-full text-[9.5px] font-semibold",
                  done && "bg-primary text-background",
                  active && "border border-primary text-primary",
                  !done && !active && "border border-line-2",
                )}
              >
                {done ? <Check className="h-2.5 w-2.5" /> : i + 1}
              </span>
              <span>{label}</span>
            </div>
            {i < steps.length - 1 && (
              <span
                className={cn(
                  "h-px w-4",
                  done ? "bg-primary/50" : "bg-line-2",
                )}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}
