import { afterEach, expect, it, vi } from 'vitest'
import {
  addProduct, getHistory, getProducts, money, numeric, utcDate, validProductUrl,
} from './products'

afterEach(() => vi.unstubAllGlobals())

it.each([
  'https://amazon.pl/dp/B012345678',
  'HTTPS://WWW.AMAZON.PL/gp/product/b012345678?tag=test&x=%20',
])('accepts supported product URL %s', url => {
  expect(validProductUrl(url)).toBe(true)
})

it.each([
  'http://amazon.pl/dp/B012345678',
  'https://amazon.pl.evil.test/dp/B012345678',
  'https://amazon.pl:443/dp/B012345678',
  'https://user@amazon.pl/dp/B012345678',
  'https://amazon.pl/../dp/B012345678',
  'https://amazon.pl/DP/B012345678',
  'https://amazon.pl/dp/B012345678/',
  'https://amazon.pl/dp/B012345678#',
  'https://amazon.pl/dp/B012345678?x=%GG',
  'https://amazon.pl/dp/B012345678?x=é',
  'https://amazon.pl/dp/B01234567ſ',
  'https://amazon.pl/dp/B012345678\n',
  ' https://amazon.pl/dp/B012345678',
])('rejects unsupported URL %s', url => {
  expect(validProductUrl(url)).toBe(false)
})

it('loads products and PLN history with cancellation', async () => {
  const fetch = vi.fn().mockImplementation(async () => new Response('[]'))
  vi.stubGlobal('fetch', fetch)
  const signal = new AbortController().signal
  await getProducts(signal)
  await getHistory(7, signal)
  expect(fetch.mock.calls).toEqual([
    ['/api/products', { signal }],
    ['/api/products/7/history?currency=PLN', { signal }],
  ])
})

it('posts the URL as JSON and returns duplicate feedback', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(
    '{"detail":"duplicate_asin"}', { status: 409 },
  ))
  vi.stubGlobal('fetch', fetch)
  const url = 'https://amazon.pl/dp/B012345678'
  await expect(addProduct(url)).rejects.toThrow('już monitorowany')
  expect(fetch).toHaveBeenCalledWith('/api/products', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
})

it('does not send invalid URLs', async () => {
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  await expect(addProduct('https://evil.test')).rejects.toThrow('Amazon.pl')
  expect(fetch).not.toHaveBeenCalled()
})

it('handles non-JSON API failures', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('offline', { status: 503 })))
  await expect(getProducts()).rejects.toThrow('Żądanie nie powiodło się (HTTP 503)')
})

it('preserves missing prices and zero and interprets backend dates as UTC', () => {
  expect(numeric(null)).toBeNull()
  expect(numeric('0.00')).toBe(0)
  expect(money(null)).toBe('Brak ceny')
  expect(money('0.00')).toContain('0,00')
  expect(utcDate('2026-01-01T12:00:00').toISOString()).toBe('2026-01-01T12:00:00.000Z')
})
