import { createClient } from "@supabase/supabase-js"

/**
 * Supabase client — used for auth only (signUp, signInWithPassword, verifyOtp,
 * session management). Backend Postgres reads/writes still go through our
 * FastAPI server; this client never touches application tables.
 *
 * The frontend requires two env vars in `.env` at the frontend/ root:
 *   VITE_SUPABASE_URL       e.g. https://abcdefgh.supabase.co
 *   VITE_SUPABASE_ANON_KEY  the project's anon (public) key
 */
const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

if (!url || !anonKey) {
  throw new Error(
    "Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY. Add them to frontend/.env " +
      "(values come from Supabase Dashboard → Project Settings → API).",
  )
}

export const supabase = createClient(url, anonKey, {
  auth: {
    // Tokens live in localStorage; refresh runs automatically. The session
    // length itself (e.g. 30 days sliding) is configured in the Supabase
    // dashboard under Authentication → Settings.
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
    storageKey: "trademark.auth",
  },
})
