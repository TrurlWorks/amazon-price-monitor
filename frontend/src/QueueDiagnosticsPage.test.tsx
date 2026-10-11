import { renderToStaticMarkup } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, it, vi } from 'vitest'
import { QueueDiagnosticsPage } from './QueueDiagnosticsPage'
import { scheduleQueueProduct, type QueueDiagnostics } from './products'

it('shows queued products, last outcome, upcoming time and history', () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const data: QueueDiagnostics = {
    as_of: '2026-10-08T10:00:00', global_available_at: '2026-10-08T10:03:00',
    cooldown_until: null, attempts_total: 1,
    items: [{
      product_id: 1, asin: 'B012345678', title: 'Monitor', image_url: 'https://example.test/image.jpg', is_active: true,
      pause_reason: null, kind: 'regular', due_at: '2026-10-08T12:00:00', planned_at: '2026-10-08T12:03:00',
      override_at: null, started_at: null, last_checked_at: '2026-10-08T09:00:00',
      last_attempt_at: '2026-10-08T09:00:00', last_outcome: 'success',
    }],
    recent_attempts: [{
      id: 1, product_id: 1, asin: 'B012345678', title: 'Monitor',
      kind: 'regular', started_at: '2026-10-08T09:00:00',
      finished_at: '2026-10-08T09:00:10', outcome: 'success',
    }],
  }
  client.setQueryData(['queue', 0], data)
  const html = renderToStaticMarkup(<QueryClientProvider client={client}>
    <QueueDiagnosticsPage />
  </QueryClientProvider>)
  for (const text of ['Kolejka odświeżania cen', 'Plan odświeżeń', 'Historia prób',
    'Zmień najbliższy termin', 'Sukces', 'Monitor', 'B012345678',
    'Globalnie możliwe od', 'href="#/settings"', 'Planowany odczyt', 'src="https://example.test/image.jpg"',
    'line-clamp-2', 'title="Monitor"']) {
    expect(html).toContain(text)
  }
  client.clear()
})

it('sends an aware one-shot time for a single product', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', fetch)
  try {
    await scheduleQueueProduct(7, '2026-10-08T12:00:00.000Z')
    expect(fetch).toHaveBeenCalledWith('/api/queue/7/schedule', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scheduled_at: '2026-10-08T12:00:00.000Z' }),
    })
  } finally {
    vi.unstubAllGlobals()
  }
})
