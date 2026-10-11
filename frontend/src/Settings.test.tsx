import { renderToStaticMarkup } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, it, vi } from 'vitest'
import { Settings, intervalSeconds } from './Settings'
import { getSettings, updateSettings, type SettingsResponse } from './products'

it('loads public settings, offers retry on failure and never renders credential values', async () => {
  // Explicit fetchQuery calls populate the cache; static renders only observe it.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, enabled: false } },
  })
  const render = () => renderToStaticMarkup(
    <QueryClientProvider client={client}><Settings /></QueryClientProvider>,
  )
  const data: SettingsResponse = {
    application_version: '0.8.4',
    display_mode: 'tiles',
    product_provider: 'mock',
    amazon_credentials_configured: false,
    poll_interval_seconds: 3600,
    failed_retry_seconds: 90,
    status: 'ok',
    product_count: 0,
    snapshot_count: 12,
  }
  const privateValue = 'fixture-private-credential'
  const fetch = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: privateValue }), { status: 503 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ...data, amazon_client_secret: privateValue,
    })))
  vi.stubGlobal('fetch', fetch)
  try {
    expect(render()).toContain('Wczytywanie ustawień')
    const signal = new AbortController().signal
    const load = () => client.fetchQuery({
      queryKey: ['settings'], queryFn: () => getSettings(signal),
    })
    await expect(load()).rejects.toThrow('Żądanie nie powiodło się (HTTP 503)')
    const failed = render()
    expect(failed).toContain('Nie udało się wczytać ustawień')
    expect(failed).toContain('Ponów wczytywanie')
    expect(failed).not.toContain(privateValue)

    await load()
    expect(fetch.mock.calls).toEqual([
      ['/api/settings', { signal }],
      ['/api/settings', { signal }],
    ])
    const html = render()
    for (const text of ['Źródło danych</dt><dd>Dane testowe', 'skonfigurowane</dt><dd>Nie',
      'Wersja aplikacji</dt><dd>0.8.4', 'Zapisz ustawienia', 'step="any"',
      'href="#/settings/queue"',
      'Widok produktów</dt><dd>Kafelki', 'value="table"',
      'Odstęp między sprawdzeniami (godziny)</dt><dd>1', 'Stan API</dt><dd>Odpowiada',
      'Ponowna próba po błędzie (minuty)</dt><dd>1.5',
      'Liczba produktów</dt><dd>0', 'Liczba obserwacji</dt><dd>12', 'href="#/"']) {
      expect(html).toContain(text)
    }
    expect(html).not.toContain('Wczytywanie ustawień')
    expect(html).not.toContain('Ponów wczytywanie')
    expect(html).not.toContain(privateValue)
    expect(html).not.toContain('amazon_client_secret')
    client.setQueryData(['settings'], { ...data, amazon_credentials_configured: true })
    expect(render()).toContain('skonfigurowane</dt><dd>Tak')
  } finally {
    client.clear()
    vi.unstubAllGlobals()
  }
})

it('converts displayed hours and minutes to whole API seconds', () => {
  expect(intervalSeconds('1', 'hours')).toBe(3600)
  expect(intervalSeconds('0.25', 'hours')).toBe(900)
  expect(intervalSeconds('1.5', 'minutes')).toBe(90)
})

it('sends only editable settings in the PUT request', async () => {
  const updated: SettingsResponse = {
    application_version: '0.8.4', display_mode: 'table', product_provider: 'mock',
    amazon_credentials_configured: false, poll_interval_seconds: 7200,
    failed_retry_seconds: 120, status: 'ok', product_count: 0, snapshot_count: 0,
  }
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(updated)))
  vi.stubGlobal('fetch', fetch)
  try {
    await expect(updateSettings({
      poll_interval_seconds: 7200, failed_retry_seconds: 120, display_mode: 'table',
    })).resolves.toEqual(updated)
    expect(fetch).toHaveBeenCalledWith('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        poll_interval_seconds: 7200, failed_retry_seconds: 120, display_mode: 'table',
      }),
    })
  } finally {
    vi.unstubAllGlobals()
  }
})
