import { afterEach, expect, it, vi } from 'vitest'
import { getHealth } from './api'

afterEach(() => vi.unstubAllGlobals())

it('requests the same-origin health endpoint and forwards cancellation', async () => {
  const fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ status: 'ok', database: 'ok' })),
  )
  vi.stubGlobal('fetch', fetch)
  const signal = new AbortController().signal
  await expect(getHealth(signal)).resolves.toEqual({ status: 'ok', database: 'ok' })
  expect(fetch).toHaveBeenCalledWith('/api/health', { signal })
})

it('rejects failed HTTP responses', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 503 })))
  await expect(getHealth()).rejects.toThrow('Service unavailable')
})

it('rejects an unexpected API contract', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}')))
  await expect(getHealth()).rejects.toThrow('Invalid health response')
})

it('propagates network failures', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Network error')))
  await expect(getHealth()).rejects.toThrow('Network error')
})
