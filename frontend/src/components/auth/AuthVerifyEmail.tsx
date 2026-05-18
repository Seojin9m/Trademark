import { useEffect, useRef, useState } from "react"
import type { ClipboardEvent, KeyboardEvent } from "react"
import { Loader2 } from "lucide-react"
import { useAuth } from "@/contexts/auth-context"
import { AuthBrandPanel } from "./AuthBrandPanel"
import { AuthStepper } from "./AuthStepper"
import { cn } from "@/lib/utils"

interface Props {
  email: string
  onDone: () => void
  onBack: () => void
  onChangeEmail: () => void
}

/**
 * Step 2: 6-digit email OTP. Supabase sends the code automatically when a
 * signUp call is made with email confirmation enabled. The "Resend" path
 * uses `supabase.auth.resend({ type: 'signup' })`.
 */
export function AuthVerifyEmail({ email, onDone, onBack, onChangeEmail }: Props) {
  const { verifyEmailOtp, resendOtp } = useAuth()
  const [digits, setDigits] = useState<string[]>(Array(6).fill(""))
  const [resendIn, setResendIn] = useState(45)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputs = useRef<Array<HTMLInputElement | null>>([])

  useEffect(() => {
    inputs.current[0]?.focus()
  }, [])

  useEffect(() => {
    if (resendIn <= 0) return
    const t = setTimeout(() => setResendIn((s) => s - 1), 1000)
    return () => clearTimeout(t)
  }, [resendIn])

  const submit = async (code?: string) => {
    const value = code ?? digits.join("")
    if (value.length < 6) return setError("Enter all 6 digits.")
    setBusy(true)
    setError(null)
    try {
      const { error } = await verifyEmailOtp(email, value)
      if (error) {
        setError(error.message || "Invalid code")
        setDigits(Array(6).fill(""))
        inputs.current[0]?.focus()
        return
      }
      onDone()
    } finally {
      setBusy(false)
    }
  }

  const setDigit = (i: number, v: string) => {
    const cleaned = v.replace(/\D/g, "").slice(-1)
    const next = [...digits]
    next[i] = cleaned
    setDigits(next)
    setError(null)
    if (cleaned && i < 5) inputs.current[i + 1]?.focus()
    if (cleaned && i === 5 && next.every(Boolean)) submit(next.join(""))
  }

  const onKey = (i: number, e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace" && !digits[i] && i > 0) inputs.current[i - 1]?.focus()
  }

  const onPaste = (e: ClipboardEvent<HTMLDivElement>) => {
    const text = (e.clipboardData.getData("text") || "").replace(/\D/g, "").slice(0, 6)
    if (!text) return
    e.preventDefault()
    const next = text.split("").concat(Array(6).fill("")).slice(0, 6)
    setDigits(next)
    const lastIdx = Math.min(text.length, 5)
    inputs.current[lastIdx]?.focus()
    if (text.length === 6) submit(text)
  }

  const resend = async () => {
    if (resendIn > 0) return
    setResendIn(45)
    setDigits(Array(6).fill(""))
    inputs.current[0]?.focus()
    const { error } = await resendOtp(email)
    if (error) setError(error.message)
  }

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <AuthBrandPanel />
      <div className="flex flex-1 items-center justify-center px-6 py-10 sm:px-10">
        <div className="w-full max-w-[440px]">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-muted-foreground">
              STEP 2 OF 3
            </span>
            <button
              onClick={onBack}
              className="rounded-[4px] border border-line-2 px-2 py-1 font-mono text-[10.5px] text-muted-foreground hover:text-foreground"
            >
              ← Back
            </button>
          </div>

          <AuthStepper current={1} mode="signup" />

          <div className="mb-5">
            <div className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              ◆ VERIFY EMAIL
            </div>
            <h2 className="mt-1 text-[26px] font-semibold tracking-[-0.02em]">Check your inbox</h2>
            <p className="mt-1 text-[13px] text-muted-foreground">
              We sent a 6-digit code to <b className="text-foreground">{email || "you@firm.com"}</b>.
              It expires in 10 minutes.
            </p>
          </div>

          <div onPaste={onPaste} className="mb-3 flex gap-2">
            {digits.map((d, i) => (
              <input
                key={i}
                ref={(el) => {
                  inputs.current[i] = el
                }}
                type="text"
                inputMode="numeric"
                maxLength={1}
                value={d}
                onChange={(e) => setDigit(i, e.target.value)}
                onKeyDown={(e) => onKey(i, e)}
                className={cn(
                  "h-12 w-12 rounded-[5px] border bg-bg-2 text-center font-mono text-[18px] font-semibold tabular-nums outline-none transition-colors",
                  error ? "border-loss" : d ? "border-primary" : "border-line-2",
                  "focus:border-primary",
                )}
              />
            ))}
          </div>

          {error && (
            <div className="mb-2 rounded-[4px] border border-loss/40 bg-loss/10 px-3 py-2 text-[12px] text-loss">
              {error}
            </div>
          )}

          <button
            onClick={() => submit()}
            disabled={busy}
            className="flex h-10 w-full items-center justify-center gap-2 rounded-[5px] bg-primary text-[13px] font-semibold text-background transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {busy ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Verifying…
              </>
            ) : (
              "Verify & continue →"
            )}
          </button>

          <div className="mt-4 flex items-center justify-between text-[12px]">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Didn't get the code?</span>
              {resendIn > 0 ? (
                <span className="font-mono text-[10.5px] tracking-[0.08em] text-muted-2">
                  RESEND IN {String(resendIn).padStart(2, "0")}s
                </span>
              ) : (
                <button onClick={resend} className="font-semibold text-primary hover:underline">
                  RESEND CODE
                </button>
              )}
            </div>
            <button onClick={onChangeEmail} className="font-mono text-[10.5px] text-muted-foreground hover:text-foreground">
              CHANGE EMAIL
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
