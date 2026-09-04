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

/** DELETE endpoints return 204 with no body -- request()'s response.json()
 * would throw on that, so this skips parsing entirely rather than reusing it. */
const del = async (path: string): Promise<void> => {
  const response = await fetch(`${API_BASE}${path}`, { method: 'DELETE' })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail ?? detail
    } catch {
      // no JSON body -- fall back to statusText, already set above
    }
    throw new ApiError(detail, response.status)
  }
}

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
  product_id: string | null
  /** The matched product's standardized name, or raw_product_text when
   * there's no match yet -- always prefer this over raw_product_text for
   * display, so Orders and Inventory show the same name for one purchase. */
  product_name: string | null
  profile: string | null
  /** Normalized retailer derived from `site` (see backend retailers.py). */
  retailer: string | null
  thumbnail_url: string | null
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
  /** 'ups' | 'fedex' | 'usps' | 'dhl', detected from the tracking number's
   * format -- null when the format isn't distinctive enough to be sure. */
  carrier: string | null
  carrier_label: string | null
  /** Deep link to the carrier's own tracking page; null when carrier is. */
  tracking_url: string | null
  /** Null until a live tracking provider is configured -- nothing offline
   * can know a delivery estimate. See backend app/tracking.py. */
  estimated_delivery: string | null
  tracking_detail: string | null
  tracking_checked_at: string | null
  /** Set when shipping_status entered 'delivered' or 'exception'. */
  shipping_alert_at: string | null
  shipping_alert_seen_at: string | null
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
  product_id: string | null
  location: string | null
  cost_basis: number | null
  listed_price: number | null
  listed_platform: string | null
  sold_price: number | null
  sold_at: string | null
  sold_platform: string | null
  /** When the money actually landed. Selling and getting paid are separate
   * events (often weeks apart on consignment payouts): status='sold' with
   * this null means sold-but-unpaid. */
  money_received_at: string | null
  notes: string | null
  created_at: string
}

export type InventoryItemUpdate = Partial<
  Omit<InventoryItem, 'id' | 'order_id' | 'unit_index' | 'created_at'>
> & {
  /** Convenience toggle -- the backend turns this into a money_received_at
   * timestamp (or clears it), so the UI never has to invent a date. */
  money_received?: boolean
}

export interface InventoryItemCreate {
  product_text: string
  quantity?: number
  status?: InventoryStatus
  cost_basis?: number | null
  location?: string | null
  notes?: string | null
}

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

export interface BulkResult {
  updated: number
}

export type ChannelScope = 'all' | 'specific'

export interface DiscordStatus {
  configured: boolean
  token_suffix: string | null
  guild_id: string | null
  channel_scope: ChannelScope | null
  channel_ids: string | null
  profile_filter: string | null
}

export interface DiscordConfigIn {
  token?: string
  guild_id: string
  channel_scope: ChannelScope
  channel_ids?: string
  profile_filter?: string
}

export type OrderSort =
  | 'date_desc'
  | 'date_asc'
  | 'price_desc'
  | 'price_asc'
  | 'product_asc'
  | 'retailer_asc'

export interface DeletedSummary {
  dismissed: number
  rebuildable: number
}

export interface RebuildResult {
  rebuilt: number
  skipped: number
}

export interface BotServiceStatus {
  supported: boolean
  installed: boolean
  running: boolean
  log_path: string | null
}

export interface Product {
  id: string
  canonical_name: string
  normalized_key: string
  category: string | null
  alias_count: number
}

/** One row of the grouped inventory view -- "I hold 12 of these". */
export interface ProductGroup {
  product_id: string | null
  name: string | null
  total_units: number
  in_hand: number
  listed: number
  sold: number
  total_cost_basis: number
  total_sold_revenue: number
  awaiting_payment: number
  /** null when nothing's sold yet -- distinct from 0 (which would claim
   * units sold for free). */
  avg_sale_price: number | null
  /** sum(sold_price - cost_basis) over sold, priced units only -- null
   * under the same rule as avg_sale_price (nothing sold yet, not "sold at
   * a $0 profit"). */
  total_profit: number | null
  image_url: string | null
  category: string | null
}

export interface CatalogSyncResult {
  sets: number
  sets_failed: number
  products_upserted: number
}

export interface CatalogMatchResult {
  auto_confirmed: number
  suggested: number
  unmatched: number
}

export interface CatalogSuggestion {
  product_id: string
  our_name: string
  candidate_id: string
  candidate_name: string
  candidate_image_url: string | null
  candidate_set: string | null
}

export interface CatalogCandidate {
  id: string
  name: string
  image_url: string | null
  set_name: string | null
  score: number
}

export interface MergeSuggestion {
  source_id: string
  target_id: string
  source_name: string
  target_name: string
  reason: string
}

export interface ProductRebuildResult {
  orders_resolved: number
  items_resolved: number
  products: number
  suggestions: number
}

export interface SyncSourceStatus {
  id: string
  name: string
  last_synced_at: string | null
}

export interface SyncStatus {
  pending: boolean
  requested_at: string | null
  full: boolean
  sources: SyncSourceStatus[]
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
    list: (filters?: {
      /** One status, or several comma-separated ("failed,cancelled"). */
      status?: string
      source_id?: string
      retailer?: string
      search?: string
      sort?: OrderSort
      limit?: number
    }) => {
      const params = new URLSearchParams()
      if (filters?.status) params.set('status', filters.status)
      if (filters?.source_id) params.set('source_id', filters.source_id)
      if (filters?.retailer) params.set('retailer', filters.retailer)
      if (filters?.search) params.set('search', filters.search)
      if (filters?.sort) params.set('sort', filters.sort)
      if (filters?.limit) params.set('limit', String(filters.limit))
      const qs = params.toString()
      return get<Order[]>(`/orders${qs ? `?${qs}` : ''}`)
    },
    get: (id: string) => get<Order>(`/orders/${id}`),
    create: (order: OrderCreate) => post<Order>('/orders', order),
    update: (id: string, patchBody: OrderUpdate) => patch<Order>(`/orders/${id}`, patchBody),
    delete: (id: string) => del(`/orders/${id}`),
    bulkDelete: (ids: string[]) => post<BulkResult>('/orders/bulk-delete', { ids }),
    bulkSetStatus: (ids: string[], status: OrderStatus) =>
      post<BulkResult>('/orders/bulk-status', { ids, status }),
    deletedSummary: () => get<DeletedSummary>('/orders/deleted-summary'),
    /** Delivered / exception alerts. Unseen only unless includeSeen. */
    shippingAlerts: (includeSeen = false) =>
      get<Order[]>(`/orders/shipping-alerts${includeSeen ? '?include_seen=true' : ''}`),
    /** Empty `ids` acknowledges every outstanding alert (mark all read). */
    ackShippingAlerts: (ids: string[] = []) =>
      post<BulkResult>('/orders/shipping-alerts/ack', { ids }),
    backfillCarriers: () => post<BulkResult>('/orders/backfill-carriers'),
    // Orders are hard deleted; rebuild re-creates them from the stored
    // ingest payloads (local -- no Discord round-trip). See backend
    // models.IngestedMessage.
    rebuild: (sourceId?: string) =>
      post<RebuildResult>('/orders/rebuild', { source_id: sourceId ?? null })
  },

  inventory: {
    list: (status?: InventoryStatus) =>
      get<InventoryItem[]>(`/inventory${status ? `?status=${status}` : ''}`),
    create: (body: InventoryItemCreate) => post<InventoryItem[]>('/inventory', body),
    summary: () => get<InventorySummary>('/inventory/summary'),
    get: (id: string) => get<InventoryItem>(`/inventory/${id}`),
    update: (id: string, patchBody: InventoryItemUpdate) =>
      patch<InventoryItem>(`/inventory/${id}`, patchBody),
    delete: (id: string) => del(`/inventory/${id}`),
    bulkDelete: (ids: string[]) => post<BulkResult>('/inventory/bulk-delete', { ids }),
    bulkSetStatus: (ids: string[], status: InventoryStatus) =>
      post<BulkResult>('/inventory/bulk-status', { ids, status }),
    restore: (ids: string[]) => post<BulkResult>('/inventory/restore', { ids })
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

  discord: {
    status: () => get<DiscordStatus>('/discord/status'),
    configure: (body: DiscordConfigIn) => post<DiscordStatus>('/discord/configure', body)
  },

  products: {
    list: () => get<Product[]>('/products'),
    grouped: () => get<ProductGroup[]>('/products/grouped'),
    suggestions: () => get<MergeSuggestion[]>('/products/suggestions'),
    rebuild: () => post<ProductRebuildResult>('/products/rebuild'),
    merge: (sourceId: string, targetId: string) =>
      post<BulkResult>('/products/merge', { source_id: sourceId, target_id: targetId }),
    rename: (id: string, canonicalName: string, category?: string | null) =>
      patch<Product>(`/products/${id}`, { canonical_name: canonicalName, category })
  },

  sync: {
    status: () => get<SyncStatus>('/sync/status'),
    request: (full = true) => post<SyncStatus>('/sync/request', { full })
  },

  catalog: {
    sync: (category: string) =>
      post<CatalogSyncResult>('/catalog/sync', { category }),
    match: () => post<CatalogMatchResult>('/catalog/match'),
    suggestions: () => get<CatalogSuggestion[]>('/catalog/suggestions'),
    candidates: (productId: string) =>
      get<CatalogCandidate[]>(`/catalog/suggestions/${productId}/candidates`),
    confirm: (productId: string, catalogProductId: string) =>
      post<Product>(`/catalog/suggestions/${productId}/confirm`, {
        catalog_product_id: catalogProductId
      }),
    reject: (productId: string) =>
      post<BulkResult>(`/catalog/suggestions/${productId}/reject`)
  },

  botService: {
    status: () => get<BotServiceStatus>('/discord/service/status'),
    install: () => post<BotServiceStatus>('/discord/service/install'),
    uninstall: () => post<BotServiceStatus>('/discord/service/uninstall'),
    restart: () => post<BotServiceStatus>('/discord/service/restart')
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
