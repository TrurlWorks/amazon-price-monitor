export interface Product {
  id: number
  asin: string
  amazon_url: string
  title: string | null
  image_url: string | null
  created_at: string
  first_seen_at: string
  last_checked_at: string | null
  status: 'ACTIVE' | 'UNAVAILABLE' | 'NOT_FOUND' | 'UNKNOWN'
  is_active: boolean
  pause_reason: 'manual' | 'automatic' | null
  next_check_at: string | null
  queue_state: 'regular' | 'manual' | 'retry' | 'recovery' | 'checking' | null
  consecutive_failures: number
  automatic_failures: number
  consecutive_not_found: number
}

export interface Snapshot {
  id: number
  product_id: number
  price: string | null
  currency: string
  seller: string | null
  availability: string | null
  is_buy_box: boolean | null
  checked_at: string
}

export interface History {
  product_id: number
  currency: string
  snapshots: Snapshot[]
  stats: {
    current: string | null
    initial: string | null
    change_amount: string | null
    change_percent: string | null
    minimum: string | null
    maximum: string | null
    average: string | null
    minimum_at: string | null
    maximum_at: string | null
  }
}

const messages: Record<string, string> = {
  product_not_found: 'Ten produkt już nie istnieje na liście.',
  duplicate_asin: 'Ten produkt jest już monitorowany.',
  invalid_product_url: 'Podaj obsługiwany adres HTTPS produktu z Amazon.pl.',
  provider_product_not_found: 'Nie znaleziono produktu w źródle danych.',
  provider_unavailable: 'Źródło danych jest niedostępne. Spróbuj ponownie później.',
  provider_temporary_failure: 'Sprawdzenie produktu nie powiodło się. Spróbuj ponownie.',
  refresh_in_progress: 'Ten produkt jest już sprawdzany. Spróbuj ponownie za chwilę.',
  schedule_conflict: 'Nie można zmienić terminu: produkt jest wyłączony albo właśnie sprawdzany.',
  invalid_schedule: 'Wybierz termin od 1 minuty do 365 dni od teraz.',
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options)
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail = body && typeof body === 'object' && 'detail' in body
      ? body.detail : null
    throw new Error(
      typeof detail === 'string' && messages[detail]
        ? messages[detail] : `Żądanie nie powiodło się (HTTP ${response.status}). Spróbuj ponownie.`,
    )
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export interface SettingsResponse {
  application_version: string
  display_mode: 'tiles' | 'table'
  product_provider: string
  amazon_credentials_configured: boolean
  poll_interval_seconds: number
  failed_retry_seconds: number
  status: 'ok'
  product_count: number
  snapshot_count: number
}

export interface SettingsUpdate {
  poll_interval_seconds: number
  failed_retry_seconds: number
  display_mode?: 'tiles' | 'table'
}

export function getSettings(signal?: AbortSignal): Promise<SettingsResponse> {
  return request('/api/settings', { signal })
}

export interface QueueItem {
  product_id: number
  asin: string
  title: string | null
  image_url: string | null
  is_active: boolean
  pause_reason: 'manual' | 'automatic' | null
  kind: 'regular' | 'manual' | 'retry' | 'recovery' | null
  due_at: string | null
  planned_at: string | null
  override_at: string | null
  started_at: string | null
  last_checked_at: string | null
  last_attempt_at: string | null
  last_outcome: string | null
}

export interface QueueAttempt {
  id: number
  product_id: number
  asin: string
  title: string | null
  kind: string
  started_at: string
  finished_at: string | null
  outcome: string
}

export interface QueueDiagnostics {
  as_of: string
  global_available_at: string
  cooldown_until: string | null
  items: QueueItem[]
  recent_attempts: QueueAttempt[]
  attempts_total: number
}

export function getQueueDiagnostics(offset = 0, signal?: AbortSignal): Promise<QueueDiagnostics> {
  return request(`/api/queue?limit=20&offset=${offset}`, { signal })
}

export function scheduleQueueProduct(id: number, scheduledAt: string): Promise<void> {
  return request(`/api/queue/${id}/schedule`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scheduled_at: scheduledAt }),
  })
}

export function updateSettings(settings: SettingsUpdate): Promise<SettingsResponse> {
  return request('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  })
}

export function getProducts(signal?: AbortSignal): Promise<Product[]> {
  return request('/api/products', { signal })
}

export function getHistory(id: number, signal?: AbortSignal): Promise<History> {
  return request(`/api/products/${id}/history?currency=PLN`, { signal })
}

export function getProduct(id: number, signal?: AbortSignal): Promise<Product> {
  return request(`/api/products/${id}`, { signal })
}

export function refreshProduct(id: number): Promise<Product> {
  return request(`/api/products/${id}/refresh`, { method: 'POST' })
}

export function refreshProductNow(id: number): Promise<Product> {
  return request(`/api/products/${id}/refresh-now`, { method: 'POST' })
}

export function setMonitoring(id: number, active: boolean): Promise<Product> {
  return request(`/api/products/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_active: active }),
  })
}

export function deleteProduct(id: number): Promise<void> {
  return request(`/api/products/${id}`, { method: 'DELETE' })
}

export function validProductUrl(value: string): boolean {
  const match = /^(https):\/\/(amazon\.pl|www\.amazon\.pl)(\/[^?]*)(?:\?(.*))?$/i.exec(value)
  if (!match || !/^\/(?:dp|gp\/product)\/[A-Za-z0-9]{10}$/.test(match[3])) return false
  return /^(?:[A-Za-z0-9\-._~!$&'()*+,;=:@/?]|%[A-Fa-f0-9]{2})*$/.test(match[4] ?? '')
}

export function addProduct(url: string): Promise<Product> {
  if (!validProductUrl(url)) return Promise.reject(new Error(messages.invalid_product_url))
  return request('/api/products', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
}

export function numeric(value: string | null | undefined): number | null {
  if (value == null || value.trim() === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export function money(value: string | null | undefined): string {
  const number = numeric(value)
  return number === null ? 'Brak ceny' : new Intl.NumberFormat('pl-PL', {
    style: 'currency', currency: 'PLN',
  }).format(number)
}

export function utcDate(value: string): Date {
  return new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`)
}

export function queueLabel(product: Product): string | null {
  if (product.queue_state === 'checking') return 'Sprawdzanie ceny…'
  if (product.queue_state === 'manual') return 'W kolejce do sprawdzenia'
  if (!product.next_check_at) return null
  const time = utcDate(product.next_check_at).toLocaleString('pl-PL')
  if (product.queue_state === 'recovery') return `Próba powrotu najwcześniej ${time}`
  if (product.queue_state === 'retry') return `Ponowna próba najwcześniej ${time}`
  return `Następne sprawdzenie najwcześniej ${time}`
}
