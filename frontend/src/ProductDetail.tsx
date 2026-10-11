import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import {
  deleteProduct, getHistory, getProduct, money, numeric, refreshProductNow,
  setMonitoring, queueLabel, utcDate, type History,
} from './products'
import { historyTimestamp, historyWindow, ranges, type HistoryRange } from './history'
import { PageFrame } from './PageFrame'

const button = 'rounded-xl bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-blue-700'
const statuses = {
  ACTIVE: 'Dostępny', UNAVAILABLE: 'Niedostępny',
  NOT_FOUND: 'Nie znaleziono', UNKNOWN: 'Nieznana dostępność',
}

export function DetailHistory({ history }: { history: History }) {
  const [range, setRange] = useState<HistoryRange>('ALL')
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000)
    return () => window.clearInterval(timer)
  }, [])
  const snapshots = historyWindow(history.snapshots, range, now)
  const points = snapshots.map(snapshot => ({
    time: utcDate(snapshot.checked_at).getTime(), price: numeric(snapshot.price),
  }))
  const { stats } = history
  const change = numeric(stats.change_amount)
  const percent = numeric(stats.change_percent)
  const direction = change === null ? 'Brak danych o zmianie' :
    change < 0 ? 'Spadek ceny' : change > 0 ? 'Wzrost ceny' : 'Bez zmian'
  const all = historyWindow(history.snapshots, 'ALL', now)
  const latest = all[all.length - 1]
  return <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/40 dark:border-slate-800 dark:bg-slate-900 dark:shadow-none sm:p-6" aria-labelledby="history-heading">
    <h2 id="history-heading" className="text-2xl font-semibold tracking-tight">Historia cen · PLN</h2>
    <p className="mt-2">Sprzedawca przy ostatniej obserwacji: {latest?.seller || 'Nieznany sprzedawca'}</p>
    <p className="mt-2 text-sm text-slate-600">Statystyki obejmują całą zapisaną historię w PLN. Zakres czasu zmienia wykres i listę obserwacji.</p>
    <dl className="my-5 grid grid-cols-2 gap-3 sm:grid-cols-3 [&>div]:rounded-xl [&>div]:bg-slate-50 [&>div]:p-4 dark:[&>div]:bg-slate-800/60 [&_dt]:text-sm [&_dt]:text-slate-500 dark:[&_dt]:text-slate-400 [&_dd]:mt-2">
      {[
        ['Bieżąca cena', stats.current], ['Cena początkowa', stats.initial],
        ['Cena minimalna', stats.minimum], ['Cena maksymalna', stats.maximum],
        ['Średnia cena', stats.average],
      ].map(([label, value]) => <div key={label}>
        <dt>{label}</dt><dd className="font-semibold">{money(value)}</dd>
      </div>)}
      <div><dt>Zmiana od początku</dt><dd>
        {direction}{change !== null && `: ${money(stats.change_amount)}`}
        {' · '}{percent === null ? 'Brak danych procentowych' : `${percent.toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`}
      </dd></div>
    </dl>
    <div role="group" aria-label="Zakres historii" className="flex flex-wrap gap-2">
      {ranges.map(value => <button key={value} className={`rounded-lg px-3 py-2 text-sm font-semibold ${range === value ? 'bg-blue-700 text-white' : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200'}`}
        aria-pressed={range === value}
        onClick={() => { setNow(Date.now()); setRange(value) }}>
        {value === 'ALL' ? 'Cała historia' : value}{range === value ? ' (wybrany)' : ''}
      </button>)}
    </div>
    <p role="status" className="my-3">Liczba obserwacji: {snapshots.length} · Zakres: {range === 'ALL' ? 'cała historia' : range}</p>
    {points.some(point => point.price !== null) ? <figure>
      <figcaption>Zaobserwowane ceny w PLN; przerwy oznaczają brak ceny.</figcaption>
      <div className="h-72 w-full min-w-0" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 16, right: 24, bottom: 16, left: 8 }}>
            <XAxis dataKey="time" type="number" domain={['dataMin', 'dataMax']}
              tickFormatter={value => new Date(Number(value)).toLocaleDateString('pl-PL')} />
            <YAxis domain={['auto', 'auto']} width={80} />
            <Tooltip labelFormatter={value => new Date(Number(value)).toLocaleString('pl-PL')} />
            <Line dataKey="price" name="Cena (PLN)" stroke="#1d4ed8" type="linear"
              dot={{ r: 3 }} connectNulls={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure> : <p className="my-4">Brak obserwacji z ceną w tym zakresie.</p>}
    <details className="mt-4">
      <summary className="cursor-pointer underline">Pokaż obserwacje cen</summary>
      <ul className="mt-3 max-h-72 overflow-auto">
        {snapshots.map(snapshot => <li key={snapshot.id}>
          {historyTimestamp(snapshot.checked_at)}: {money(snapshot.price)}
          {' · '}{snapshot.seller || 'Nieznany sprzedawca'}
        </li>)}
      </ul>
    </details>
  </section>
}

export function ProductDetail({ id }: { id: number }) {
  const client = useQueryClient()
  const heading = useRef<HTMLHeadingElement>(null)
  const [imageFailed, setImageFailed] = useState(false)
  const [notice, setNotice] = useState('')
  const product = useQuery({
    queryKey: ['product', id], queryFn: ({ signal }) => getProduct(id, signal),
    refetchInterval: 30_000,
  })
  const history = useQuery({
    queryKey: ['history', id, 'PLN'], queryFn: ({ signal }) => getHistory(id, signal),
    refetchInterval: 30_000,
  })
  useEffect(() => { heading.current?.focus() }, [id])
  useEffect(() => { setImageFailed(false) }, [product.data?.image_url])
  async function invalidate() {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['products'] }),
      client.invalidateQueries({ queryKey: ['product', id] }),
      client.invalidateQueries({ queryKey: ['history', id] }),
    ])
  }
  const action = useMutation({
    mutationFn: async (kind: 'refresh' | 'toggle' | 'delete') => {
      if (kind === 'delete') return deleteProduct(id)
      if (kind === 'refresh') return refreshProductNow(id)
      if (!product.data) throw new Error('Wczytaj produkt przed zmianą monitorowania.')
      return setMonitoring(id, !product.data.is_active)
    },
    onMutate: () => setNotice(''),
    onSuccess: async (updated, kind) => {
      if (kind === 'delete') {
        await Promise.all([
          client.cancelQueries({ queryKey: ['product', id] }),
          client.cancelQueries({ queryKey: ['history', id] }),
        ])
        client.removeQueries({ queryKey: ['product', id] })
        client.removeQueries({ queryKey: ['history', id] })
        window.location.hash = '#/'
      } else {
        client.setQueryData(['product', id], updated)
        setNotice(kind === 'refresh' ? 'Cena została sprawdzona.' : 'Monitorowanie zaktualizowane.')
      }
    },
    onSettled: async (_data, _error, kind) => {
      // Failed acquisition also changes status and last_checked_at on the server.
      if (kind === 'delete') await client.invalidateQueries({ queryKey: ['products'] })
      else await invalidate()
    },
  })
  const data = product.data
  return <PageFrame><main className="mx-auto max-w-5xl px-4 py-9 sm:px-8">
    <a href="#/" className="text-sm font-medium text-blue-700 underline dark:text-blue-300">Wróć do produktów</a>
    <a href="#/settings" className="ml-4 text-sm font-medium text-blue-700 underline dark:text-blue-300">Ustawienia</a>
    <p className="mt-7 text-xs font-semibold uppercase tracking-[0.2em] text-blue-700 dark:text-blue-300">Szczegóły produktu · Amazon.pl</p>
    <h1 ref={heading} tabIndex={-1} className="mb-6 mt-2 break-words text-3xl font-bold tracking-tight sm:text-4xl">
      {data?.title || data?.asin || 'Szczegóły produktu'}
    </h1>
    {product.isPending && <p role="status">Wczytywanie produktu…</p>}
    {product.isError && <div role="alert">
      <p>{product.error.message} {data && 'Pokazano ostatnio wczytane informacje o produkcie.'}</p>
      <button className={button} onClick={() => void product.refetch()}>Ponów wczytywanie produktu</button>
    </div>}
    {data && <><section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/40 dark:border-slate-800 dark:bg-slate-900 dark:shadow-none sm:p-6">
      {data.image_url && !imageFailed ? <img src={data.image_url} alt=""
        referrerPolicy="no-referrer" onError={() => setImageFailed(true)}
        className="mb-4 h-48 w-48 max-w-full object-contain" /> : <p>Brak zdjęcia</p>}
      <div className="grid gap-3 text-sm sm:grid-cols-2">
        <p><span className="text-slate-500 dark:text-slate-400">ASIN:</span> {data.asin}</p>
        <p><span className="text-slate-500 dark:text-slate-400">Dostępność:</span> {statuses[data.status]}</p>
        <p><span className="text-slate-500 dark:text-slate-400">Monitorowanie:</span> {data.is_active ? 'aktywne' : 'wstrzymane'}</p>
        <p><span className="text-slate-500 dark:text-slate-400">Ostatnie sprawdzenie:</span> {historyTimestamp(data.last_checked_at)}</p>
      </div>
      {data.consecutive_failures > 0 && <p className="text-amber-900">Ostatnie sprawdzenie nie powiodło się. Ceny pochodzą z wcześniejszych obserwacji.</p>}
      {data.pause_reason === 'automatic' && <p role="alert" className="mt-3 text-amber-900 dark:text-amber-300">Monitorowanie zostało wstrzymane po dwóch nieudanych ponowieniach. Produkt pozostaje w kolejce rzadkich prób powrotu.</p>}
      {queueLabel(data) && <p role="status" className="mt-3 text-sm text-slate-600 dark:text-slate-300">{queueLabel(data)}</p>}
      <div className="my-5 flex flex-wrap items-center gap-3">
        <button className={button} disabled={action.isPending} onClick={() => action.mutate('refresh')}>Sprawdź teraz</button>
        <button className={button} disabled={action.isPending} onClick={() => action.mutate('toggle')}>
          {data.is_active ? 'Wstrzymaj monitorowanie' : 'Wznów monitorowanie'}
        </button>
        <button className={button} disabled={action.isPending} onClick={() => {
          if (window.confirm(`Usunąć produkt ${data.title || data.asin} (${data.asin}) wraz z całą historią cen? Tej operacji nie można cofnąć.`)) action.mutate('delete')
        }}>Usuń produkt</button>
        <a href={data.amazon_url} target="_blank" rel="noopener noreferrer" className="text-sm font-semibold text-blue-700 underline dark:text-blue-300">Otwórz w Amazon.pl (nowa karta)</a>
      </div>
      <p role="status">{action.isPending ? action.variables === 'refresh' ? 'Sprawdzanie ceny…' : 'Zapisywanie…' : notice}</p>
      {action.isError && <p role="alert">{action.error.message}</p>}
      </section>
      {history.isPending && <p role="status">Wczytywanie historii cen…</p>}
      {history.isError && <div role="alert">
        <p>Nie udało się wczytać historii cen. {history.data && 'Pokazano ostatnio wczytane ceny.'}</p>
        <button className={button} onClick={() => void history.refetch()}>Ponów wczytywanie historii</button>
      </div>}
      {history.data && <DetailHistory history={history.data} />}
    </>}
  </main></PageFrame>
}
