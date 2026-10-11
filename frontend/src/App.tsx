import { useSyncExternalStore } from 'react'
import { ProductDetail } from './ProductDetail'
import { PreviewDashboard } from './PreviewDashboard'
import { Settings } from './Settings'
import { QueueDiagnosticsPage } from './QueueDiagnosticsPage'
import { InfoPage } from './InfoPage'

export function productIdFromHash(hash: string): number | null {
  const match = /^#\/products\/([1-9]\d*)$/.exec(hash)
  const id = match ? Number(match[1]) : NaN
  return Number.isSafeInteger(id) ? id : null
}

function subscribe(callback: () => void) {
  window.addEventListener('hashchange', callback)
  return () => window.removeEventListener('hashchange', callback)
}

export function App() {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash, () => '')
  return <Route hash={hash} />
}

export function Route({ hash }: { hash: string }) {
  const id = productIdFromHash(hash)
  if (hash === '#/preview') return <PreviewDashboard />
  if (hash === '#/settings') return <Settings />
  if (hash === '#/settings/queue') return <QueueDiagnosticsPage />
  if (hash === '#/info') return <InfoPage />
  if (id !== null) return <ProductDetail key={id} id={id} />
  if (hash && hash !== '#/' && hash !== '#') {
    return <main className="mx-auto max-w-7xl p-8">
      <h1 className="text-2xl font-bold">Nie znaleziono strony</h1>
      <a href="#/" className="underline">Wróć do produktów</a>
    </main>
  }
  return <PreviewDashboard />
}
