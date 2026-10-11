import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getSettings, updateSettings } from './products'
import { PageFrame } from './PageFrame'

const statCard = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/40 dark:border-slate-800 dark:bg-slate-900 dark:shadow-none [&>dt]:text-sm [&>dt]:text-slate-500 [&>dd]:mt-2 [&>dd]:font-semibold'

export function intervalSeconds(value: string, unit: 'hours' | 'minutes'): number {
  return Math.round(Number(value) * (unit === 'hours' ? 3600 : 60))
}

function displayInterval(seconds: number, unit: 'hours' | 'minutes'): string {
  return String(seconds / (unit === 'hours' ? 3600 : 60))
}

function providerLabel(provider: string): string {
  if (provider === 'amazon_page') return 'Strona Amazon.pl'
  if (provider === 'mock') return 'Dane testowe'
  return provider
}

export function Settings() {
  const client = useQueryClient()
  const [pollHours, setPollHours] = useState<string | null>(null)
  const [failedMinutes, setFailedMinutes] = useState<string | null>(null)
  const [displayMode, setDisplayMode] = useState<'tiles' | 'table' | null>(null)
  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: ({ signal }) => getSettings(signal),
    retry: false,
  })
  const data = settings.data
  const save = useMutation({
    mutationFn: updateSettings,
    onSuccess: updated => {
      setPollHours(displayInterval(updated.poll_interval_seconds, 'hours'))
      setFailedMinutes(displayInterval(updated.failed_retry_seconds, 'minutes'))
      setDisplayMode(updated.display_mode)
      client.setQueryData(['settings'], updated)
      void client.invalidateQueries({ queryKey: ['settings'] })
    },
  })
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!data) return
    save.reset()
    save.mutate({
      poll_interval_seconds: intervalSeconds(pollHours ?? displayInterval(data.poll_interval_seconds, 'hours'), 'hours'),
      failed_retry_seconds: intervalSeconds(failedMinutes ?? displayInterval(data.failed_retry_seconds, 'minutes'), 'minutes'),
      display_mode: displayMode ?? data.display_mode,
    })
  }
  return <PageFrame><main className="mx-auto max-w-5xl px-4 py-9 sm:px-8">
    <a href="#/" className="text-sm font-medium text-blue-700 underline dark:text-blue-300">Wróć do produktów</a>
    <p className="mt-7 text-xs font-semibold uppercase tracking-[0.2em] text-blue-700 dark:text-blue-300">Monitor cen · Amazon.pl</p>
    <h1 className="mt-2 text-3xl font-bold tracking-tight sm:text-4xl">Ustawienia</h1>
    <p className="mb-7 mt-2 text-sm text-slate-600 dark:text-slate-300">Konfiguracja aplikacji i informacje o jej stanie.</p>
    <a href="#/settings/queue" className="mb-6 inline-flex rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 font-semibold text-blue-800 hover:bg-blue-100 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-200">Diagnostyka kolejki i terminy odświeżeń →</a>
    {settings.isPending && <p role="status">Wczytywanie ustawień…</p>}
    {settings.isError && <div role="alert">
      <p>Nie udało się wczytać ustawień. {data && 'Pokazano ostatnio wczytane ustawienia.'}</p>
      <button type="button" disabled={settings.isFetching}
        className="my-3 rounded-lg bg-slate-900 px-4 py-3 text-white dark:bg-slate-200 dark:text-slate-900 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-blue-700 dark:focus-visible:outline-blue-300"
        onClick={() => void settings.refetch()}>
        {settings.isFetching ? 'Ponawianie…' : 'Ponów wczytywanie'}
      </button>
    </div>}
    {data && <>
      <form className="mb-5 grid gap-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm shadow-slate-200/40 sm:grid-cols-2 dark:border-slate-800 dark:bg-slate-900 dark:shadow-none"
        onSubmit={submit}>
        <label className="grid gap-2">Odstęp między sprawdzeniami (godziny)
          <input type="number" min={String(1 / 60)} step="any" required
            value={pollHours ?? displayInterval(data.poll_interval_seconds, 'hours')}
            onChange={event => { save.reset(); setPollHours(event.target.value) }}
            className="rounded-xl border border-slate-300 bg-white px-3 py-2.5 dark:border-slate-700 dark:bg-slate-950" />
        </label>
        <label className="grid gap-2">Ponowna próba po błędzie (minuty)
          <input type="number" min="1" step="any" required
            value={failedMinutes ?? displayInterval(data.failed_retry_seconds, 'minutes')}
            onChange={event => { save.reset(); setFailedMinutes(event.target.value) }}
            className="rounded-xl border border-slate-300 bg-white px-3 py-2.5 dark:border-slate-700 dark:bg-slate-950" />
        </label>
        <p className="text-sm text-slate-500 dark:text-slate-400 sm:col-span-2">Automatyczne odczyty i dodawanie produktów przechodzą przez kolejkę. „Sprawdź teraz” w szczegółach wykonuje odczyt od razu i przesuwa kolejny start workera. Po błędzie automatycznym są najwyżej dwa ponowienia z rosnącym odstępem; potem produkt czeka na rzadką próbę powrotu. Globalna przerwa jest ustawiana na serwerze.</p>
        <label className="grid gap-2">Widok produktów
          <select value={displayMode ?? data.display_mode}
            onChange={event => { save.reset(); setDisplayMode(event.target.value as 'tiles' | 'table') }}
            className="rounded-xl border border-slate-300 bg-white px-3 py-2.5 dark:border-slate-700 dark:bg-slate-950">
            <option value="tiles">Kafelki</option>
            <option value="table">Tabela</option>
          </select>
        </label>
        <div className="sm:col-span-2">
          <button type="submit" disabled={save.isPending}
            className="rounded-xl bg-blue-700 px-5 py-2.5 font-semibold text-white hover:bg-blue-800 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-blue-700">
            {save.isPending ? 'Zapisywanie…' : 'Zapisz ustawienia'}
          </button>
          {save.isSuccess && <p role="status" className="mt-3 text-green-700 dark:text-green-300">Ustawienia zapisane.</p>}
          {save.isError && <p role="alert" className="mt-3 text-red-700 dark:text-red-300">Nie udało się zapisać ustawień. Spróbuj ponownie.</p>}
        </div>
      </form>
      <dl className="grid gap-3 sm:grid-cols-2">
        <div className={statCard}><dt>Wersja aplikacji</dt><dd>{data.application_version}</dd></div>
        <div className={statCard}><dt>Widok produktów</dt><dd>{data.display_mode === 'tiles' ? 'Kafelki' : 'Tabela'}</dd></div>
        <div className={statCard}><dt>Źródło danych</dt><dd>{providerLabel(data.product_provider)}</dd></div>
        <div className={statCard}><dt>Dane dostępowe Amazon skonfigurowane</dt>
          <dd>{data.amazon_credentials_configured ? 'Tak' : 'Nie'}</dd></div>
        <div className={statCard}><dt>Odstęp między sprawdzeniami (godziny)</dt><dd>{displayInterval(data.poll_interval_seconds, 'hours')}</dd></div>
        <div className={statCard}><dt>Ponowna próba po błędzie (minuty)</dt><dd>{displayInterval(data.failed_retry_seconds, 'minutes')}</dd></div>
        <div className={statCard}><dt>Stan API</dt><dd>{data.status === 'ok' ? 'Odpowiada' : data.status}</dd></div>
        <div className={statCard}><dt>Liczba produktów</dt><dd>{data.product_count}</dd></div>
        <div className={statCard}><dt>Liczba obserwacji</dt><dd>{data.snapshot_count}</dd></div>
      </dl>
      <p className="mt-4 text-sm text-slate-600">
        Informacja o danych dostępowych oznacza tylko ich obecność, nie poprawność. Stan API
        nie potwierdza działania procesu pobierania danych. Liczby obejmują także wstrzymane
        produkty i wszystkie obserwacje.
      </p>
    </>}
  </main></PageFrame>
}
