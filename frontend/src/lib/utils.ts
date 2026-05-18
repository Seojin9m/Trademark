import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"
import { supabase } from "@/lib/supabase"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(value)
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

export function formatNumber(value: number, decimals = 2): string {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value)
}

export function pnlColor(value: number): string {
  if (value > 0) return "text-profit"
  if (value < 0) return "text-loss"
  return "text-neutral"
}

// Backend origin. Default empty so dev keeps using the Vite proxy at /api;
// in production, set VITE_API_URL to the deployed backend (e.g.
// https://api.trade4me.app) and the proxy becomes irrelevant.
const API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "") + "/api"

// Shared secret proving "this request is from the deployed Trademark frontend"
// — checked by the backend AppTokenMiddleware before any per-user logic.
const APP_TOKEN = import.meta.env.VITE_APP_TOKEN as string | undefined
if (!APP_TOKEN) {
  // Surface this loudly during dev so misconfigured envs don't silently 401
  // every request.
  console.warn(
    "VITE_APP_TOKEN is not set. Add it to frontend/.env to match the backend's APP_API_TOKEN.",
  )
}

/** Build the headers used by both apiFetch and the raw-fetch helpers. */
export async function buildAuthHeaders(extra?: HeadersInit): Promise<Headers> {
  const headers = new Headers(extra)
  if (APP_TOKEN) headers.set("X-App-Token", APP_TOKEN)
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  if (token) headers.set("Authorization", `Bearer ${token}`)
  return headers
}

/** Absolute URL for an API path. Use to build URLs that bypass apiFetch
 *  (EventSource, file downloads, etc). */
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`
}

/** App-token query-string suffix for EventSource and other contexts that
 *  can't set request headers. Returns "" if no token is configured. */
export function appTokenQuery(): string {
  return APP_TOKEN ? `app_token=${encodeURIComponent(APP_TOKEN)}` : ""
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  // Attach both the static app token (proves we're the deployed frontend) and
  // the per-user Supabase JWT (identifies the user). Public endpoints ignore
  // the JWT; per-user endpoints reject calls without it.
  const headers = await buildAuthHeaders(options?.headers)

  const res = await fetch(apiUrl(path), { ...options, headers })
  if (!res.ok) {
    let detail = `API error: ${res.status}`
    try {
      const body = await res.json()
      detail = body.detail || body.error || body.message || detail
    } catch {
      // response wasn't JSON
    }
    throw new Error(detail)
  }
  return res.json()
}
