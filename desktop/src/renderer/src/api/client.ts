/**
 * client.ts
 * ---------
 * A single typed client for the FastAPI backend -- every screen imports
 * from here rather than hand-rolling fetch() calls. Types mirror
 * backend/app/schemas.py field-for-field; when the backend's shape
 * changes, this is the one file that needs updating to match.
 */

const API_BASE = 'http://127.0.0.1:8000'

/** Thrown by every failed request -- `.status` lets a caller branch on a
 * specific code (e.g. backup restore's 409 schema mismatch) instead of
 * string-matching the message. */
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

// ---------------------------------------------------------------------------
// Shared request helpers
// ---------------------------------------------------------------------------

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init)
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail ?? detail
    } catch {
      // response wasn't JSON -- fall back to statusText, already set above
    }
    throw new ApiError(detail, response.status)
  }
  return response.json() as Promise<T>
}

const get = <T>(path: string): Promise<T> => request<T>(path)

const post = <T>(path: string, body?: unknown): Promise<T> =>
  request<T>(path, {
    method: 'POST',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined
  })

const patch = <T>(path: string, body: unknown): Promise<T> =>
  request<T>(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })

const put = <T>(path: string, body: unknown): Promise<T> =>
  request<T>(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })

const postForm = <T>(path: string, form: FormData): Promise<T> =>
  request<T>(path, { method: 'POST', body: form })

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

export interface HealthStatus {
  status: string
}

export interface CurrentUser {
  id: string
  email: string
}

export type OrderStatus = 'success' | 'failed' | 'cancelled' | 'pending'
export type ShippingStatus = 'not_shipped' | 'label_created' | 'in_transit' | 'delivered' | 'exception'
export type InventoryStatus = 'in_hand' | 'listed' | 'sold' | 'returned' | 'lost'

export interface Source {
  id: string
  type: string
  name: string
  config: Record<string, unknown>
  last_synced_at: string | null
  created_at: string
}

export interface Order {
  id: string
  source_id: string
  external_id: string
  status: OrderStatus
  failure_reason: string | null
  raw_product_text: string | null
  profile: string | null
  site: string | null
  module: string | null
  category: string | null
  quantity: number | null
  unit_price: number | null
  currency: string
  order_number: string | null
  order_url: string | null
  shipping_status: ShippingStatus
  tracking_number: string | null
  ship_to_label: string | null
  ship_to_address: string | null
  purchased_at: string | null
  created_at: string
}

export type OrderCreate = Partial<
  Omit<Order, 'id' | 'created_at' | 'shipping_status'>
> &
  Pick<Order, 'source_id' | 'external_id' | 'status'> & { shipping_status?: ShippingStatus }

export type OrderUpdate = Partial<Omit<Order, 'id' | 'source_id' | 'external_id' | 'created_at' | 'currency' | 'module'>>

export interface InventoryItem {
  id: string
  order_id: string | null
  unit_index: number | null
  status: InventoryStatus
  product_text: string | null
  cost_basis: number | null
  listed_price: number | null
  listed_platform: string | null
  sold_price: number | null
  sold_at: string | null
  sold_platform: string | null
  notes: string | null
  created_at: string
}

export type InventoryItemUpdate = Partial<
  Omit<InventoryItem, 'id' | 'order_id' | 'unit_index' | 'created_at'>
>

export interface InventorySummary {
  total_units: number
  in_hand: number
  listed: number
  sold: number
  total_cost_basis: number
  total_sold_revenue: number
  est_inventory_value: number
  order_count: number
}

export interface MonthlyPoint {
  month: string
  spend: number
  revenue: number
}

export interface AgingBucket {
  label: string
  min_days: number
  max_days: number | null
  count: number
}

export interface AgingSummary {
  buckets: AgingBucket[]
  value_tied_up_60d_plus: number
}

export interface RetailerBreakdown {
  site: string
  order_count: number
}

export interface CategoryBreakdown {
  category: string
  unit_count: number
  total_spend: number
  total_profit: number
}

export interface Setting<T = Record<string, unknown>> {
  key: string
  value: T
  updated_at: string
}

export interface LicenseStatus {
  activated: boolean
  key_suffix: string | null
  activated_at: string | null
}

export interface BackupPreview {
  filename: string
  created_at: string
  backup_schema_version: string | null
  current_schema_version: string | null
  orders: number
  inventory_items: number
}

export interface RestoreResult {
  restored: boolean
  restart_required: boolean
  safety_copy: string | null
  orders: number
  inventory_items: number
}

export type ImportMode = 'purchase' | 'unit'

export interface ImportRowResult {
  row_number: number
  ok: boolean
  reason: string | null
  duplicate: boolean
  fields: Record<string, unknown>
}

export interface ImportPreview {
  filename: string
  sheet: string | null
  sheet_names: string[]
  columns: string[]
  mapping: Record<string, string | null>
  row_count: number
  ready: number
  duplicates: number
  needs_attention: number
  rows: ImportRowResult[]
}

export interface ImportCommitResult {
  source_id: string
  created_orders: number
  created_inventory_items: number
  skipped: number
  duplicates: number
}

// ---------------------------------------------------------------------------
// The client
// ---------------------------------------------------------------------------

export const api = {
  health: () => get<HealthStatus>('/health'),
  me: () => get<CurrentUser>('/me'),

  sources: {
    list: () => get<Source[]>('/sources'),
    create: (type: string, name: string, config?: Record<string, unknown>) =>
      post<Source>(
        `/sources?${new URLSearchParams({ type, name })}`,
        config ?? {}
      )
  },

  orders: {
    list: (filters?: { status?: OrderStatus; source_id?: string; limit?: number }) => {
      const params = new URLSearchParams()
      if (filters?.status) params.set('status', filters.status)
      if (filters?.source_id) params.set('source_id', filters.source_id)
      if (filters?.limit) params.set('limit', String(filters.limit))
      const qs = params.toString()
      return get<Order[]>(`/orders${qs ? `?${qs}` : ''}`)
    },
    get: (id: string) => get<Order>(`/orders/${id}`),
    create: (order: OrderCreate) => post<Order>('/orders', order),
    update: (id: string, patchBody: OrderUpdate) => patch<Order>(`/orders/${id}`, patchBody)
  },

  inventory: {
    list: (status?: InventoryStatus) =>
      get<InventoryItem[]>(`/inventory${status ? `?status=${status}` : ''}`),
    summary: () => get<InventorySummary>('/inventory/summary'),
    get: (id: string) => get<InventoryItem>(`/inventory/${id}`),
    update: (id: string, patchBody: InventoryItemUpdate) =>
      patch<InventoryItem>(`/inventory/${id}`, patchBody)
  },

  dashboard: {
    monthly: (months = 6) => get<MonthlyPoint[]>(`/dashboard/monthly?months=${months}`),
    aging: () => get<AgingSummary>('/dashboard/aging'),
    byRetailer: () => get<RetailerBreakdown[]>('/dashboard/by-retailer'),
    byCategory: () => get<CategoryBreakdown[]>('/dashboard/by-category')
  },

  settings: {
    list: () => get<Setting[]>('/settings'),
    get: <T = Record<string, unknown>>(key: string) => get<Setting<T>>(`/settings/${key}`),
    set: <T = Record<string, unknown>>(key: string, value: T) =>
      put<Setting<T>>(`/settings/${key}`, { value })
  },

  license: {
    status: () => get<LicenseStatus>('/license/status'),
    activate: (key: string) => post<LicenseStatus>('/license/activate', { key }),
    deactivate: () => post<LicenseStatus>('/license/deactivate')
  },

  backup: {
    /** Returns the .cache bundle's raw bytes plus the filename the server
     * suggested (from Content-Disposition) -- the renderer decides how to
     * hand it to the user (native save dialog via the main process, most
     * likely) since fetch() alone can't trigger one. */
    export: async (): Promise<{ blob: Blob; filename: string }> => {
      const response = await fetch(`${API_BASE}/backup/export`, { method: 'POST' })
      if (!response.ok) {
        throw new ApiError(response.statusText, response.status)
      }
      const disposition = response.headers.get('content-disposition') ?? ''
      const match = disposition.match(/filename="?([^"]+)"?/)
      const filename = match ? match[1] : 'cache-backup.cache'
      return { blob: await response.blob(), filename }
    },
    preview: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return postForm<BackupPreview>('/backup/preview', form)
    },
    restore: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return postForm<RestoreResult>('/backup/restore', form)
    }
  },

  import: {
    preview: (
      file: File,
      opts: { mode: ImportMode; sheet?: string; mapping?: Record<string, string | null> }
    ) => {
      const form = new FormData()
      form.append('file', file)
      form.append('mode', opts.mode)
      if (opts.sheet) form.append('sheet', opts.sheet)
      if (opts.mapping) form.append('mapping_json', JSON.stringify(opts.mapping))
      return postForm<ImportPreview>('/import/preview', form)
    },
    commit: (
      file: File,
      opts: { mode: ImportMode; sheet?: string; mapping: Record<string, string | null> }
    ) => {
      const form = new FormData()
      form.append('file', file)
      form.append('mode', opts.mode)
      if (opts.sheet) form.append('sheet', opts.sheet)
      form.append('mapping_json', JSON.stringify(opts.mapping))
      return postForm<ImportCommitResult>('/import/commit', form)
    }
  }
}
