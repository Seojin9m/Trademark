import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"
import { useAuth } from "@/contexts/auth-context"
import { AuthLoginSignup } from "./AuthLoginSignup"
import { AuthVerifyEmail } from "./AuthVerifyEmail"
import { AuthConnectBrokerage } from "./AuthConnectBrokerage"

type Step = "auth" | "verify" | "brokerage"
type Mode = "login" | "signup"

/**
 * Top-level auth orchestrator. Walks the user through the right sub-flow:
 *   not signed in              → AuthLoginSignup
 *   signed up, awaiting OTP    → AuthVerifyEmail
 *   signed in, no brokerage    → AuthConnectBrokerage
 *   signed in, brokerage done  → unmounted (parent renders the app)
 *
 * When `<AuthFlow>` is mounted, the parent has already decided the user
 * isn't fully onboarded; AuthFlow's job is to advance them through whatever
 * step is missing.
 */
export function AuthFlow({ onComplete }: { onComplete: () => void }) {
  const { user, loading, brokerageConnected } = useAuth()
  const [step, setStep] = useState<Step>("auth")
  const [mode, setMode] = useState<Mode>("login")
  const [draftEmail, setDraftEmail] = useState("")

  // If the user is already signed in but missing brokerage, jump straight to step 3.
  useEffect(() => {
    if (loading) return
    if (user && !brokerageConnected) setStep("brokerage")
    else if (user && brokerageConnected) onComplete()
  }, [user, brokerageConnected, loading, onComplete])

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    )
  }

  if (step === "verify") {
    return (
      <AuthVerifyEmail
        email={draftEmail}
        onDone={() => setStep("brokerage")}
        onBack={() => setStep("auth")}
        onChangeEmail={() => setStep("auth")}
      />
    )
  }

  if (step === "brokerage") {
    return (
      <AuthConnectBrokerage
        mode={mode}
        onConnected={onComplete}
        onBack={() => setStep(mode === "signup" ? "verify" : "auth")}
      />
    )
  }

  return (
    <AuthLoginSignup
      initialMode={mode}
      initialEmail={draftEmail}
      onAfterSubmit={({ mode: m, email }) => {
        setMode(m)
        setDraftEmail(email)
        // signup needs verification before brokerage; login goes straight there.
        setStep(m === "signup" ? "verify" : "brokerage")
      }}
    />
  )
}
