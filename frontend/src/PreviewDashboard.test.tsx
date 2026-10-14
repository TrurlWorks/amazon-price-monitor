import { renderToStaticMarkup } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, it } from 'vitest'
import { PreviewDashboard, matchingSuggestions, refreshResultLabel, sortedPreviewRows, visiblePreviewRows } from './PreviewDashboard'
import type { History, Product } from './products'

it('reports a retrieved price only when the newest observation contains one', () => {
  const history = { snapshots: [{ price: '99.00' }, { price: null }] } as History
  expect(refreshResultLabel(history)).toBe('Odczyt wykonany bez ceny.')
  expect(refreshResultLabel({ ...history, snapshots: [{ price: null }, { price: '98.00' }] } as History)).toBe('Cena pobrana.')
  expect(refreshResultLabel(null)).toBe('Odczyt wykonany, ale nie udało się potwierdzić ceny.')
})

it('narrows existing products by name, ASIN and attention state', () => {
  const base: Product = {
    id: 1, asin: 'B012345678', title: 'Słuchawki',
    amazon_url: 'https://www.amazon.pl/dp/B012345678', image_url: null,
    created_at: '2026-01-01T00:00:00', first_seen_at: '2026-01-01T00:00:00',
    last_checked_at: '2026-01-02T00:00:00', status: 'ACTIVE', is_active: true,
    pause_reason: null, next_check_at: null, queue_state: null,
    consecutive_failures: 0, automatic_failures: 0, consecutive_not_found: 0,
  }
  const rows = [
    { product: base },
    { product: { ...base, id: 2, asin: 'B087654321', title: 'Monitor',
      status: 'UNKNOWN' as const, consecutive_failures: 1 } },
    { product: { ...base, id: 3, asin: 'B099999999', title: 'Wstrzymany',
      is_active: false, automatic_failures: 3, pause_reason: 'automatic' as const,
      queue_state: 'recovery' as const, next_check_at: '2026-01-03T00:00:00' } },
  ]
  expect(visiblePreviewRows(rows, 'słuch', 'all').map(row => row.product.id)).toEqual([1])
  expect(visiblePreviewRows(rows, 'B087654321', 'all').map(row => row.product.id)).toEqual([2])
  expect(visiblePreviewRows(rows, '', 'attention').map(row => row.product.id)).toEqual([2, 3])
  expect(visiblePreviewRows(rows, 'Słuchawki', 'attention')).toEqual([])
  const many = Array.from({ length: 25 }, (_, index) => ({
    product: { ...base, id: index + 1, asin: `B${String(index).padStart(9, '0')}`, title: `Produkt ${index + 1}` },
  }))
  expect(matchingSuggestions(many, '')).toHaveLength(25)
  expect(matchingSuggestions(many, 'produkt 25').map(row => row.product.id)).toEqual([25])

  const sortable = [
    { product: { ...base, title: 'Żelazko' }, history: { stats: { current: '10', change_amount: '-5' } } as History },
    { product: { ...base, id: 2, title: 'Album', status: 'UNKNOWN' as const }, history: { stats: { current: null, change_amount: null } } as History },
    { product: { ...base, id: 3, title: 'Monitor', is_active: false }, history: { stats: { current: '20', change_amount: '5' } } as History },
    { product: { ...base, id: 4, title: 'Ładowarka' }, history: { stats: { current: '15', change_amount: '0' } } as History },
  ]
  const ids = (key: 'product' | 'price' | 'change' | 'status', direction: 'asc' | 'desc') =>
    sortedPreviewRows(sortable, key, direction).map(row => row.product.id)
  expect(ids('product', 'asc')).toEqual([2, 4, 3, 1])
  expect(ids('price', 'asc')).toEqual([1, 4, 3, 2])
  expect(ids('price', 'desc')).toEqual([3, 4, 1, 2])
  expect(ids('change', 'asc')).toEqual([1, 4, 3, 2])
  expect(ids('change', 'desc')).toEqual([3, 4, 1, 2])
  expect(ids('status', 'asc')).toEqual([1, 4, 2, 3])
  expect(ids('status', 'desc')).toEqual([3, 2, 1, 4])
})

it('keeps adding products and the saved display mode in the live dashboard', () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['products'], [{
    id: 1, asin: 'B012345678', title: 'Słuchawki bezprzewodowe z bardzo długą nazwą produktu',
    amazon_url: 'https://www.amazon.pl/dp/B012345678', image_url: 'https://example.test/product.jpg',
    created_at: '2026-01-01T00:00:00', first_seen_at: '2026-01-01T00:00:00',
    last_checked_at: '2026-01-02T00:00:00', status: 'ACTIVE', is_active: true,
    pause_reason: null, next_check_at: null, queue_state: null,
    consecutive_failures: 0, automatic_failures: 0, consecutive_not_found: 0,
  } satisfies Product])
  client.setQueryData(['settings'], {
    application_version: '0.8.5', display_mode: 'tiles', product_provider: 'mock',
    amazon_credentials_configured: false, poll_interval_seconds: 3600,
    failed_retry_seconds: 90, status: 'ok', product_count: 1, snapshot_count: 0,
  })
  const render = () => renderToStaticMarkup(
    <QueryClientProvider client={client}><PreviewDashboard /></QueryClientProvider>,
  )
  expect(render()).toContain('Dodaj do monitorowania')
  expect(render()).toContain('href="#/settings"')
  expect(render()).toContain('href="#/info"')
  expect(render()).toContain('href="#/products/1"')
  expect(render()).toContain('src="https://example.test/product.jpg"')
  expect(render()).toContain('Sprawdź teraz')
  expect(render()).toMatch(/aria-label="Pokaż: Monitorowane produkty" aria-pressed="true"/)
  expect(render()).toMatch(/aria-label="Pokaż: Spadek od początku" aria-pressed="false"/)
  expect(render()).toMatch(/aria-label="Pokaż: Wymagają uwagi" aria-pressed="false"/)
  expect(render()).not.toContain('aria-label="Pokaż: Ostatnia próba odczytu"')
  expect(render()).toMatch(/aria-pressed="true"[^>]*>Kafelki/)
  client.setQueryData(['settings'], {
    ...client.getQueryData<object>(['settings']), display_mode: 'table',
  })
  const table = render()
  expect(table).toMatch(/aria-pressed="true"[^>]*>Tabela/)
  expect(table).toContain('table-fixed')
  expect(table).toContain('min-w-[700px]')
  expect(table).toContain('aria-selected="true"')
  expect(table).toContain('tabindex="0"')
  expect(table).toContain('title="Słuchawki bezprzewodowe z bardzo długą nazwą produktu"')
  expect(table).toContain('src="https://example.test/product.jpg"')
  expect(table).toContain('Odczyt')
  expect(table).toContain('aria-sort="ascending"')
  expect(table).toContain('aria-label="Sortuj: Cena"')
  expect(table).toContain('aria-label="Sortowanie produktów"')
  expect(table.match(/Sprawdź teraz/g)).toHaveLength(2)
  client.setQueryData<Product[]>(['products'], previous => previous?.map(item => ({
    ...item, is_active: false, automatic_failures: 3, pause_reason: 'automatic',
    queue_state: 'recovery', next_check_at: '2026-01-03T00:00:00',
  })))
  expect(render()).toContain('Monitorowanie wstrzymane po dwóch nieudanych ponowieniach')
  client.clear()
})
