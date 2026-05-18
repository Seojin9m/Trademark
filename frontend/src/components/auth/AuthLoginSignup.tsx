import { useState } from "react"
import type { FormEvent } from "react"
import { useAuth } from "@/contexts/auth-context"
import { AuthBrandPanel } from "./AuthBrandPanel"
import { AuthStepper } from "./AuthStepper"
import { cn } from "@/lib/utils"

type Mode = "login" | "signup"

interface Props {
  initialMode?: Mode
  initialEmail?: string
  onAfterSubmit: (data: { mode: Mode; email: string; name: string }) => void
}

/**
 * Step 1 of the onboarding flow. Calls Supabase Auth directly via the
 * auth context. On success, hands off to the parent (AuthFlow) which decides
 * whether to push the user to the email-verification step or straight to
 * brokerage connect (login path skips verification).
 */
export function AuthLoginSignup({ initialMode = "login", initialEmail = "", onAfterSubmit }: Props) {
  const { signIn, signUp, signInWithGoogle } = useAuth()

  const [mode, setMode] = useState<Mode>(initialMode)
  const [email, setEmail] = useState(initialEmail)
  const [password, setPassword] = useState("")
  const [name, setName] = useState("")
  const [confirm, setConfirm] = useState("")
  const [agree, setAgree] = useState(false)
  const [remember, setRemember] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)

    if (mode === "signup") {
      if (password.length < 10) return setError("Password must be at least 10 characters.")
      if (password !== confirm) return setError("Passwords don't match.")
      if (!agree) return setError("You must agree to the Terms.")
    }

    setBusy(true)
    try {
      if (mode === "login") {
        const { error } = await signIn(email, password)
        if (error) {
          setError(error.message)
          return
        }
      } else {
        const { error } = await signUp(email, password, name)
        if (error) {
          setError(error.message)
          return
        }
      }
      onAfterSubmit({ mode, email, name })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <AuthBrandPanel />
      <div className="flex flex-1 items-center justify-center px-6 py-10 sm:px-10">
        <div className="w-full max-w-[440px]">
          <AuthStepper current={0} mode={mode} />

          <div className="mb-6">
            <div className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              ◆ {mode === "login" ? "AUTHENTICATE" : "NEW ACCOUNT"}
            </div>
            <h2 className="mt-1 text-[26px] font-semibold tracking-[-0.02em]">
              {mode === "login" ? "Sign in to Trademark" : "Create your account"}
            </h2>
            <p className="mt-1 text-[13px] text-muted-foreground">
              {mode === "login"
                ? "Welcome back."
                : "Two minutes: verify your email, then connect a brokerage."}
            </p>
          </div>

          <button
            type="button"
            onClick={() => signInWithGoogle()}
            className="mb-3 flex h-10 w-full items-center justify-center gap-2 rounded-[5px] border border-line-2 bg-surface px-4 text-[13px] font-medium transition-colors hover:bg-surface-2"
          >
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-bg-2 font-mono text-[11px] font-bold">
              G
            </span>
            Continue with Google
          </button>

          <div className="my-4 flex items-center gap-3">
            <span className="h-px flex-1 bg-line-2" />
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-2">
              OR WITH EMAIL
            </span>
            <span className="h-px flex-1 bg-line-2" />
          </div>

          <form onSubmit={submit} className="space-y-3">
            {mode === "signup" && (
              <Field label="FULL NAME">
                <input
                  type="text"
                  placeholder="Seojin Han"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className={inputCls}
                />
              </Field>
            )}

            <Field label="EMAIL">
              <input
                type="email"
                placeholder="you@firm.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoFocus
                className={inputCls}
              />
            </Field>

            <Field
              label="PASSWORD"
              right={
                mode === "login" ? (
                  <a className="font-mono text-[10px] text-muted-foreground hover:text-primary" href="#" onClick={(e) => e.preventDefault()}>
                    Forgot?
                  </a>
                ) : null
              }
            >
              <input
                type="password"
                placeholder="••••••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputCls}
              />
              {mode === "signup" && (
                <PasswordStrength value={password} />
              )}
            </Field>

            {mode === "signup" && (
              <Field label="CONFIRM PASSWORD">
                <input
                  type="password"
                  placeholder="••••••••••••"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  className={inputCls}
                />
              </Field>
            )}

            <label className="flex items-center gap-2 pt-1 text-[12px] text-muted-foreground">
              {mode === "login" ? (
                <>
                  <input
                    type="checkbox"
                    checked={remember}
                    onChange={(e) => setRemember(e.target.checked)}
                    className="h-3.5 w-3.5 accent-primary"
                  />
                  <span>Remember this device for 30 days</span>
                </>
              ) : (
                <>
                  <input
                    type="checkbox"
                    checked={agree}
                    onChange={(e) => setAgree(e.target.checked)}
                    className="h-3.5 w-3.5 accent-primary"
                  />
                  <span>
                    I agree to the{" "}
                    <a href="#" onClick={(e) => e.preventDefault()} className="text-primary hover:underline">
                      Terms
                    </a>{" "}
                    and{" "}
                    <a href="#" onClick={(e) => e.preventDefault()} className="text-primary hover:underline">
                      Privacy Policy
                    </a>
                  </span>
                </>
              )}
            </label>

            {error && (
              <div className="rounded-[4px] border border-loss/40 bg-loss/10 px-3 py-2 text-[12px] text-loss">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="mt-1 flex h-10 w-full items-center justify-center gap-2 rounded-[5px] bg-primary text-[13px] font-semibold text-background transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {busy ? "Working…" : mode === "login" ? "Continue →" : "Create account →"}
            </button>

            <div className="pt-1 text-center text-[12px] text-muted-foreground">
              <span>{mode === "login" ? "Don't have an account?" : "Already have an account?"}</span>{" "}
              <button
                type="button"
                onClick={() => setMode(mode === "login" ? "signup" : "login")}
                className="font-semibold text-primary hover:underline"
              >
                {mode === "login" ? "Sign up" : "Sign in"} →
              </button>
            </div>

            <div className="pt-3 text-center font-mono text-[10px] uppercase tracking-[0.1em] text-muted-2">
              <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-profit" />
              SECURED · 256-BIT TLS · 2FA AVAILABLE
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

const inputCls =
  "block h-10 w-full rounded-[5px] border border-line-2 bg-bg-2 px-3 font-mono text-[13px] tracking-tight outline-none transition-colors focus:border-primary"

function Field({
  label,
  right,
  children,
}: {
  label: string
  right?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <label className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
          {label}
        </label>
        {right}
      </div>
      {children}
    </div>
  )
}

function PasswordStrength({ value }: { value: string }) {
  const segments = [1, 6, 10, 14]
  const label =
    value.length === 0
      ? "MIN 10 CHARS"
      : value.length < 6
        ? "WEAK"
        : value.length < 10
          ? "OK"
          : value.length < 14
            ? "STRONG"
            : "EXCELLENT"
  return (
    <div className="mt-1.5 flex items-center gap-2">
      <div className="flex h-1 flex-1 gap-1 overflow-hidden">
        {segments.map((min, i) => (
          <span
            key={i}
            className={cn(
              "h-full flex-1 rounded-full",
              value.length >= min ? "bg-primary" : "bg-line-2",
            )}
          />
        ))}
      </div>
      <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-2">
        {label}
      </span>
    </div>
  )
}
