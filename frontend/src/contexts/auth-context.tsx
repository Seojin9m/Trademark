import { createContext, useContext, useEffect, useMemo, useState } from "react"
import type { ReactNode } from "react"
import type { AuthError, Session, User } from "@supabase/supabase-js"
import { supabase } from "@/lib/supabase"

/**
 * App-wide auth state. Holds the current Supabase session + user, exposes
 * imperative actions for the AuthFlow component to call, and tells the rest
 * of the app whether onboarding (brokerage connect) has finished.
 *
 * `brokerageConnected` is sourced from auth.users.user_metadata.has_brokerage,
 * a flag the backend flips on once the user finishes the connect step. The
 * AuthFlow keeps the user on the brokerage step until this is true.
 */
interface AuthContextValue {
  session: Session | null
  user: User | null
  loading: boolean
  brokerageConnected: boolean
  signIn: (email: string, password: string) => Promise<{ error: AuthError | null }>
  signUp: (
    email: string,
    password: string,
    name: string,
  ) => Promise<{ error: AuthError | null; needsVerification: boolean }>
  verifyEmailOtp: (email: string, token: string) => Promise<{ error: AuthError | null }>
  resendOtp: (email: string) => Promise<{ error: AuthError | null }>
  signInWithGoogle: () => Promise<{ error: AuthError | null }>
  signOut: () => Promise<void>
  markBrokerageConnected: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    supabase.auth.getSession().then(({ data }) => {
      if (cancelled) return
      setSession(data.session)
      setLoading(false)
    })

    const { data: sub } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next)
    })
    return () => {
      cancelled = true
      sub.subscription.unsubscribe()
    }
  }, [])

  const value = useMemo<AuthContextValue>(() => {
    const brokerageConnected = Boolean(
      session?.user?.user_metadata?.has_brokerage,
    )

    return {
      session,
      user: session?.user ?? null,
      loading,
      brokerageConnected,
      async signIn(email, password) {
        const { error } = await supabase.auth.signInWithPassword({ email, password })
        return { error }
      },
      async signUp(email, password, name) {
        // Supabase sends a 6-digit OTP via email when "Confirm email" is enabled
        // in the project's Authentication → Providers → Email settings.
        const { data, error } = await supabase.auth.signUp({
          email,
          password,
          options: { data: { full_name: name } },
        })
        const needsVerification =
          !error && !data.session && Boolean(data.user) && !data.user?.email_confirmed_at
        return { error, needsVerification }
      },
      async verifyEmailOtp(email, token) {
        const { error } = await supabase.auth.verifyOtp({ email, token, type: "email" })
        return { error }
      },
      async resendOtp(email) {
        const { error } = await supabase.auth.resend({ type: "signup", email })
        return { error }
      },
      async signInWithGoogle() {
        const { error } = await supabase.auth.signInWithOAuth({
          provider: "google",
          options: { redirectTo: window.location.origin },
        })
        return { error }
      },
      async signOut() {
        await supabase.auth.signOut()
      },
      async markBrokerageConnected() {
        await supabase.auth.updateUser({ data: { has_brokerage: true } })
        const { data } = await supabase.auth.getSession()
        setSession(data.session)
      },
    }
  }, [session, loading])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>")
  return ctx
}
