import { TrademarkLogo } from "@/components/layout/trademark-logo"

interface Props {
  variant?: "default" | "brokerage"
}

/**
 * Left-side brand / marketing panel shown alongside every auth screen.
 * Pure presentation — no auth logic, no network calls.
 */
export function AuthBrandPanel({ variant = "default" }: Props) {
  const isBrokerage = variant === "brokerage"

  return (
    <div className="hidden flex-col justify-between border-r border-line bg-bg-2 px-10 py-12 md:flex md:w-[44%] lg:w-[40%]">
      <div className="flex items-center gap-3">
        <TrademarkLogo size={26} showWord />
      </div>

      <div className="space-y-8">
        <div className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-2">
          QUANTITATIVE TRADING · v4.0 PHASE 9
        </div>
        <h1 className="text-[44px] font-semibold leading-[1.05] tracking-[-0.02em]">
          {isBrokerage ? (
            <>
              Wire it
              <br />
              <span className="text-primary">to your book.</span>
            </>
          ) : (
            <>
              Discipline,
              <br />
              <span className="text-primary">automated.</span>
            </>
          )}
        </h1>
        <p className="max-w-[440px] text-[13.5px] leading-relaxed text-fg-dim">
          {isBrokerage
            ? "Read-only OAuth by default. Every order requires your explicit approval. Tokens are encrypted at rest and you can disconnect any time."
            : "Factor-driven signals, LLM-judged trades, and a portfolio that learns from every decision. Trademark runs the playbook so you don't have to."}
        </p>

        <div className="flex flex-wrap gap-x-4 gap-y-2 border-y border-line py-3 font-mono text-[11px]">
          {[
            ["NVDA", "+1.84%", true],
            ["AAPL", "+0.42%", true],
            ["MSFT", "+0.18%", true],
            ["AMZN", "-0.62%", false],
            ["GOOGL", "+0.91%", true],
            ["META", "+2.14%", true],
            ["TSLA", "-1.28%", false],
          ].map(([t, d, up]) => (
            <span key={t as string} className="inline-flex items-center gap-1.5">
              <span className="text-fg-dim">{t}</span>
              <span className={up ? "text-profit" : "text-loss"}>{d}</span>
            </span>
          ))}
        </div>
      </div>

      <div className="font-mono text-[10px] tracking-[0.08em] text-muted-2">
        © 2026 Trademark · SOC 2 · Brokerage-agnostic
      </div>
    </div>
  )
}
