import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PageFrame } from './PageFrame'
import { ProductThumbnail } from './ProductThumbnail'
import {
  getQueueDiagnostics, scheduleQueueProduct, utcDate,
  type QueueAttempt, type QueueItem,
} from './products'

const card = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/40 dark:border-slate-800 dark:bg-slate-900 dark:shadow-none'

function moment(value: string | null): string {
  return value ? utcDate(value).toLocaleString('pl-PL') : '—'
}

function kindLabel(kind: string | null): string {
  return ({ regular: 'Planowe', manual: 'Ręczne', retry: 'Ponowienie', recovery: 'Próba powrotu' } as Record<string, string>)[kind ?? ''] ?? 'Brak zlecenia'
}

function outcomeLabel(outcome: string | null): string {
  return ({ success: 'Sukces', blocked: 'Blokada Amazon', not_found: 'Nie znaleziono', error: 'Błąd', interrupted: 'Przerwane', checking: 'W trakcie' } as Record<string, string>)[outcome ?? ''] ?? 'Brak zapisu'
}

function QueueRow({ item }: { item: QueueItem }) {
  const client = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [localTime, setLocalTime] = useState('')
  const save = useMutation({
    mutationFn: (value: string) => scheduleQueueProduct(item.product_id, new Date(value).toISOString()),
    onSuccess: () => {
      setEditing(false)
      setLocalTime('')
      void client.invalidateQueries({ queryKey: ['queue'] })
      void client.invalidateQueries({ queryKey: ['products'] })
    },
  })
  const canSchedule = item.kind !== null && !item.started_at && item.pause_reason !== 'manual'
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (localTime) save.mutate(localTime)
  }
  return <article className={`${card} min-w-0 overflow-hidden`}>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <ProductThumbnail key={item.image_url} url={item.image_url} />
        <div className="min-w-0 flex-1">
          <a href={`#/products/${item.product_id}`} className="line-clamp-2 break-all font-semibold text-blue-800 hover:underline dark:text-blue-300" title={item.title ?? item.asin}>
            {item.title ?? item.asin}
          </a>
          <p className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">{item.asin} · {kindLabel(item.kind)}{item.pause_reason === 'automatic' ? ' · Wymaga uwagi' : item.pause_reason === 'manual' ? ' · Wyłączony ręcznie' : ''}</p>
        </div>
      </div>
      <span className="max-w-full shrink-0 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium dark:bg-slate-800">{item.started_at ? 'Sprawdzanie' : item.override_at ? 'Termin zmieniony' : item.due_at ? 'W kolejce' : 'Bez terminu'}</span>
    </div>
    <dl className="mt-4 grid min-w-0 gap-3 text-sm sm:grid-cols-2 xl:grid-cols-4">
      <div className="min-w-0"><dt className="text-slate-500 dark:text-slate-400">Zadany termin</dt><dd className="mt-1 break-words font-medium">{moment(item.due_at)}</dd></div>
      <div className="min-w-0"><dt className="text-slate-500 dark:text-slate-400">Planowany odczyt</dt><dd className="mt-1 break-words font-semibold text-blue-800 dark:text-blue-300">{item.started_at ? 'Trwa teraz' : moment(item.planned_at)}</dd></div>
      <div className="min-w-0"><dt className="text-slate-500 dark:text-slate-400">Ostatnia próba</dt><dd className="mt-1 break-words font-medium">{moment(item.last_attempt_at ?? item.last_checked_at)}</dd></div>
      <div className="min-w-0"><dt className="text-slate-500 dark:text-slate-400">Wynik ostatniej próby</dt><dd className="mt-1 break-words font-medium">{item.last_outcome ? outcomeLabel(item.last_outcome) : item.last_checked_at ? 'Brak wyniku sprzed rewizji 0008' : 'Brak prób'}</dd></div>
    </dl>
    {canSchedule && <div className="mt-4 border-t border-slate-100 pt-4 dark:border-slate-800">
      {!editing ? <button type="button" className="text-sm font-semibold text-blue-700 hover:underline dark:text-blue-300" onClick={() => { save.reset(); setEditing(true) }}>Zmień najbliższy termin</button> :
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <label className="grid gap-1 text-sm">Nowy termin (czas lokalny)
            <input type="datetime-local" required value={localTime} onChange={event => { save.reset(); setLocalTime(event.target.value) }}
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-950" />
          </label>
          <button type="submit" disabled={save.isPending || !localTime} className="rounded-xl bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{save.isPending ? 'Zapisywanie…' : 'Zapisz termin'}</button>
          <button type="button" className="px-2 py-2.5 text-sm underline" onClick={() => setEditing(false)}>Anuluj</button>
        </form>}
      {save.isError && <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">{save.error.message}</p>}
    </div>}
  </article>
}

function AttemptRow({ attempt }: { attempt: QueueAttempt }) {
  return <li className="grid gap-2 border-b border-slate-100 py-4 text-sm last:border-0 dark:border-slate-800 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center sm:gap-5">
    <div className="min-w-0"><a href={`#/products/${attempt.product_id}`} title={attempt.title ?? attempt.asin} className="line-clamp-2 break-all font-medium text-blue-800 hover:underline dark:text-blue-300">{attempt.title ?? attempt.asin}</a><span className="block truncate text-xs text-slate-500">{attempt.asin} · {kindLabel(attempt.kind)}</span></div>
    <div><span className="text-slate-500">Start: </span>{moment(attempt.started_at)}<br /><span className="text-slate-500">Koniec: </span>{moment(attempt.finished_at)}</div>
    <strong className={attempt.outcome === 'success' ? 'text-green-700 dark:text-green-300' : attempt.outcome === 'checking' ? 'text-blue-700 dark:text-blue-300' : 'text-amber-700 dark:text-amber-300'}>{outcomeLabel(attempt.outcome)}</strong>
  </li>
}

export function QueueDiagnosticsPage() {
  const [search, setSearch] = useState('')
  const [pageSize, setPageSize] = useState(20)
  const [page, setPage] = useState(0)
  const [historyPage, setHistoryPage] = useState(0)
  const queue = useQuery({
    queryKey: ['queue', historyPage],
    queryFn: ({ signal }) => getQueueDiagnostics(historyPage * 20, signal),
    refetchInterval: 15_000,
    retry: false,
  })
  const data = queue.data
  const filtered = (data?.items ?? []).filter(item => `${item.title ?? ''} ${item.asin}`.toLocaleLowerCase('pl-PL').includes(search.toLocaleLowerCase('pl-PL')))
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const shownPage = Math.min(page, totalPages - 1)
  return <PageFrame><main className="mx-auto max-w-6xl px-4 py-9 sm:px-8">
    <a href="#/settings" className="text-sm font-medium text-blue-700 underline dark:text-blue-300">← Wróć do ustawień</a>
    <p className="mt-7 text-xs font-semibold uppercase tracking-[0.2em] text-blue-700 dark:text-blue-300">Diagnostyka</p>
    <h1 className="mt-2 text-3xl font-bold tracking-tight sm:text-4xl">Kolejka odświeżania cen</h1>
    <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">Planowany odczyt jest szacunkiem na podstawie obecnej kolejki, wspólnego odstępu i przerwy po blokadzie Amazon. Nowe zlecenia i czas pobierania mogą zmienić tę godzinę. Lista aktualizuje się co 15 sekund.</p>
    {queue.isPending && <p role="status" className="mt-8">Wczytywanie kolejki…</p>}
    {queue.isError && <div role="alert" className="mt-8">Nie udało się wczytać kolejki. <button type="button" className="underline" onClick={() => void queue.refetch()}>Spróbuj ponownie</button></div>}
    {data && <>
      <div className="mt-7 grid gap-4 sm:grid-cols-3">
        <div className={card}><p className="text-sm text-slate-500">Produkty</p><p className="mt-2 text-2xl font-bold">{data.items.length}</p></div>
        <div className={card}><p className="text-sm text-slate-500">Globalnie możliwe od</p><p className="mt-2 font-semibold">{moment(data.global_available_at)}</p></div>
        <div className={card}><p className="text-sm text-slate-500">Przerwa po blokadzie Amazon</p><p className="mt-2 font-semibold">{data.cooldown_until ? `Do ${moment(data.cooldown_until)}` : 'Brak'}</p></div>
      </div>
      <section className="mt-9" aria-labelledby="queue-heading">
        <div className="flex flex-wrap items-end justify-between gap-4"><div><h2 id="queue-heading" className="text-2xl font-bold">Plan odświeżeń</h2><p className="mt-1 text-sm text-slate-500">Zadany termin to najwcześniejszy dopuszczalny start. Zmiana terminu dotyczy tylko najbliższej próby.</p></div>
          <div className="flex flex-wrap gap-3"><label className="grid gap-1 text-sm">Szukaj produktu<input type="search" value={search} onChange={event => { setSearch(event.target.value); setPage(0) }} placeholder="Nazwa lub ASIN" className="rounded-xl border border-slate-300 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900" /></label>
            <label className="grid gap-1 text-sm">Na stronie<select value={pageSize} onChange={event => { setPageSize(Number(event.target.value)); setPage(0) }} className="rounded-xl border border-slate-300 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900"><option value={10}>10</option><option value={20}>20</option><option value={50}>50</option></select></label></div>
        </div>
        <div className="mt-5 grid gap-3">{filtered.slice(shownPage * pageSize, (shownPage + 1) * pageSize).map(item => <QueueRow key={item.product_id} item={item} />)}{filtered.length === 0 && <p className={card}>Brak pasujących produktów.</p>}</div>
        <div className="mt-4 flex items-center justify-between text-sm"><span>Strona {shownPage + 1} z {totalPages} · {filtered.length} produktów</span><div className="flex gap-2"><button type="button" disabled={shownPage === 0} onClick={() => setPage(shownPage - 1)} className="rounded-lg border px-3 py-2 disabled:opacity-40">Wstecz</button><button type="button" disabled={shownPage + 1 >= totalPages} onClick={() => setPage(shownPage + 1)} className="rounded-lg border px-3 py-2 disabled:opacity-40">Dalej</button></div></div>
      </section>
      <section className="mt-12" aria-labelledby="history-heading"><h2 id="history-heading" className="text-2xl font-bold">Historia prób</h2><p className="mt-1 text-sm text-slate-500">Wyniki są rejestrowane od rewizji 0008. Nieudana próba nie jest obserwacją ceny.</p>
        <ul className={`${card} mt-5 divide-y divide-slate-100 dark:divide-slate-800`}>{data.recent_attempts.map(attempt => <AttemptRow key={attempt.id} attempt={attempt} />)}{data.recent_attempts.length === 0 && <li className="text-sm text-slate-500">Brak zapisanych prób.</li>}</ul>
        <div className="mt-4 flex items-center justify-between text-sm"><span>{data.attempts_total} zapisanych prób · strona {historyPage + 1}</span><div className="flex gap-2"><button type="button" disabled={historyPage === 0} onClick={() => setHistoryPage(historyPage - 1)} className="rounded-lg border px-3 py-2 disabled:opacity-40">Wstecz</button><button type="button" disabled={(historyPage + 1) * 20 >= data.attempts_total} onClick={() => setHistoryPage(historyPage + 1)} className="rounded-lg border px-3 py-2 disabled:opacity-40">Dalej</button></div></div>
      </section>
    </>}
  </main></PageFrame>
}
