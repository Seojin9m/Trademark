import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

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

const API_BASE = "/api"

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, options)
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
