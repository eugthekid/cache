/**
 * api.ts
 * ------
 * A thin client for the FastAPI backend. Centralizing the base URL and
 * fetch logic here means every screen calls the same handful of functions
 * instead of hand-rolling fetch() calls everywhere.
 */

const API_BASE = 'http://127.0.0.1:8000'

export interface HealthStatus {
  status: string
}

export interface CurrentUser {
  id: string
  email: string
}

export interface InventorySummary {
  total_units: number
  in_hand: number
  listed: number
  sold: number
  total_cost_basis: number
  total_sold_revenue: number
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => get<HealthStatus>('/health'),
  me: () => get<CurrentUser>('/me'),
  inventorySummary: () => get<InventorySummary>('/inventory/summary')
}
