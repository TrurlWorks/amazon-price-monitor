import { renderToStaticMarkup } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { productIdFromHash } from './App'
import { DetailHistory, ProductDetail } from './ProductDetail'
import { historyWindow, ranges } from './history'
import {
  deleteProduct, getProduct, refreshProduct, refreshProductNow, setMonitoring,
  type History, type Product, type Snapshot,
} from './products'

afterEach(() => vi.unstubAllGlobals())

const product: Product = {
  id: 7, asin: 'B012345678', title: 'Test product',
  amazon_url: 'https://www.amazon.pl/dp/B012345678', image_url: null,
  created_at: '2026-01-01T00:00:00', first_seen_at: '2026-01-01T00:00:00',
  last_checked_at: null, status: 'UNKNOWN', is_active: false,
  pause_reason: 'manual', next_check_at: null, queue_state: null,
  consecutive_failures: 0, automatic_failures: 0, consecutive_not_found: 0,
}
const history: History = {
  product_id: 7, currency: 'PLN', snapshots: [],
  stats: {
    current: null, initial: '0.00', change_amount: null, change_percent: null,
    minimum: '0.00', maximum: '20.00', average: '10.00',
    minimum_at: null, maximum_at: null,
  },
}
const snapshot = (id: number, checked_at: string, price: string | null): Snapshot => ({
  id, product_id: 7, checked_at, price, currency: 'PLN',
  seller: 'Example seller', availability: null, is_buy_box: null,
})

it('recognizes detail links and rejects malformed or unsafe IDs', () => {
  expect(productIdFromHash('#/products/7')).toBe(7)
  for (const hash of ['', '#/', '#/products/0', '#/products/-1',
    '#/products/1x', '#/products/1/extra', '#/products/9007199254740992']) {
    expect(productIdFromHash(hash)).toBeNull()
  }
})

it.each(ranges.filter(range => range !== 'ALL'))('filters %s relative to now inclusively', range => {
  const days = { '24h': 1, '7d': 7, '30d': 30, '90d': 90 }
  const now = Date.parse('2026-09-18T12:00:00Z')
  const cutoff = now - days[range] * 86_400_000
  const items = [
    snapshot(3, new Date(now).toISOString(), null),
    snapshot(2, new Date(cutoff).toISOString(), '0.00'),
    snapshot(1, new Date(cutoff - 1).toISOString(), '20.00'),
    snapshot(4, new Date(now + 1).toISOString(), '30.00'),
  ]
  expect(historyWindow(items, range, now).map(item => item.id)).toEqual([2, 3])
  expect(items.map(item => item.id)).toEqual([3, 2, 1, 4])
})

it('ALL retains old observations, nulls, zero prices and timestamp ties in ID order', () => {
  const items = [
    snapshot(2, '2026-01-01T00:00:00', null),
    snapshot(1, '2026-01-01T00:00:00', '0.00'),
  ]
  expect(historyWindow(items, 'ALL', Date.now()).map(item => item.price)).toEqual(['0.00', null])
})

it('renders all API statistics, missing values and accessible range controls', () => {
  const html = renderToStaticMarkup(<DetailHistory history={history} />)
  for (const text of ['Bieżąca cena', 'Cena początkowa', 'Cena maksymalna', 'Średnia cena',
    '20,00', '10,00', 'Brak ceny', 'Brak danych o zmianie', 'Brak danych procentowych',
    'Brak obserwacji z ceną', 'Nieznany sprzedawca', 'aria-pressed="true"',
    ...ranges.filter(range => range !== 'ALL'), 'Cała historia']) {
    expect(html).toContain(text)
  }
})

it('renders loading and cached detail information with navigation and actions', () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const render = () => renderToStaticMarkup(
    <QueryClientProvider client={client}><ProductDetail id={7} /></QueryClientProvider>,
  )
  expect(render()).toContain('Wczytywanie produktu')
  client.setQueryData(['product', 7], product)
  client.setQueryData(['history', 7, 'PLN'], history)
  const html = render()
  for (const text of ['Test product', 'B012345678', 'Brak zdjęcia', 'Nieznana dostępność',
    'Jeszcze nie sprawdzono', 'Wznów monitorowanie', 'Sprawdź teraz', 'Usuń produkt',
    'Otwórz w Amazon.pl', 'href="#/"']) expect(html).toContain(text)
  client.setQueryData(['product', 7], { ...product, automatic_failures: 3,
    pause_reason: 'automatic', queue_state: 'recovery', next_check_at: '2026-01-02T00:00:00' })
  expect(render()).toContain('Monitorowanie zostało wstrzymane')
  client.clear()
})

it('uses the detail, refresh, toggle and empty DELETE response contracts', async () => {
  const fetch = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(product)))
    .mockResolvedValueOnce(new Response(JSON.stringify(product)))
    .mockResolvedValueOnce(new Response(JSON.stringify(product)))
    .mockResolvedValueOnce(new Response(JSON.stringify(product)))
    .mockResolvedValueOnce(new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', fetch)
  const signal = new AbortController().signal
  expect(await getProduct(7, signal)).toEqual(product)
  await refreshProduct(7)
  await refreshProductNow(7)
  await setMonitoring(7, false)
  await expect(deleteProduct(7)).resolves.toBeUndefined()
  expect(fetch.mock.calls).toEqual([
    ['/api/products/7', { signal }],
    ['/api/products/7/refresh', { method: 'POST' }],
    ['/api/products/7/refresh-now', { method: 'POST' }],
    ['/api/products/7', { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: '{"is_active":false}' }],
    ['/api/products/7', { method: 'DELETE' }],
  ])
})

it('reports missing products without confusing them with provider absence', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
    '{"detail":"product_not_found"}', { status: 404 },
  )))
  await expect(getProduct(7)).rejects.toThrow('już nie istnieje')
})
