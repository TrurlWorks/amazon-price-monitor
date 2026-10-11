import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { addProduct, getHistory, getProducts, getSettings, numeric, refreshProductNow, updateSettings,
  queueLabel, utcDate, validProductUrl, type History, type Product } from './products'
import { ThemeToggle } from './theme'
import { ProductThumbnail } from './ProductThumbnail'

type PreviewRow = { product: Product, history?: History, loading?: boolean, error?: boolean, retry?: () => void }
type Segment = 'all' | 'drops' | 'attention' | 'paused'

const statusNames: Record<Product['status'], string> = {
  ACTIVE: 'Dostępny', UNAVAILABLE: 'Niedostępny',
  NOT_FOUND: 'Nie znaleziono', UNKNOWN: 'Nieznana dostępność',
}

function timeLabel(value: string | null): string {
  if (!value) return 'Brak odczytu'
  const date = utcDate(value)
  return Number.isNaN(date.getTime()) ? 'Nieznana data' : date.toLocaleString('pl-PL')
}

function displayMoney(value: string | null | undefined): string {
  const amount = numeric(value)
  return amount === null ? 'Brak ceny' : new Intl.NumberFormat('pl-PL', {
    style: 'currency', currency: 'PLN',
  }).format(amount)
}

function priceChange(history?: History): number | null {
  return numeric(history?.stats.change_amount)
}

export function refreshResultLabel(history: History | null): string {
  if (!history) return 'Odczyt wykonany, ale nie udało się potwierdzić ceny.'
  return numeric(history.snapshots.at(-1)?.price) === null
    ? 'Odczyt wykonany bez ceny.' : 'Cena pobrana.'
}

function RefreshNowButton({ product }: { product: Product }) {
  const client = useQueryClient()
  const [result, setResult] = useState('')
  const refresh = useMutation({
    mutationFn: async () => {
      const updated = await refreshProductNow(product.id)
      const history = await getHistory(product.id).catch(() => null)
      return { updated, history }
    },
    onMutate: () => setResult(''),
    onSuccess: ({ updated, history }) => {
      client.setQueryData(['product', product.id], updated)
      client.setQueryData<Product[]>(['products'], previous => previous?.map(item =>
        item.id === updated.id ? updated : item))
      if (history) client.setQueryData(['history', product.id, 'PLN'], history)
      setResult(refreshResultLabel(history))
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['products'] })
      void client.invalidateQueries({ queryKey: ['product', product.id] })
      void client.invalidateQueries({ queryKey: ['history', product.id] })
    },
  })
  return <div className="min-w-0">
    <button type="button" disabled={refresh.isPending || product.queue_state === 'checking'}
      onClick={event => { event.stopPropagation(); refresh.mutate() }}
      className="max-w-full rounded-lg border border-blue-300 px-2 py-1.5 text-xs font-semibold leading-tight text-blue-700 hover:bg-blue-50 disabled:opacity-50 dark:border-blue-700 dark:text-blue-300 dark:hover:bg-blue-950">
      {refresh.isPending ? 'Sprawdzanie ceny…' : 'Sprawdź teraz'}
    </button>
    {refresh.isPending && <p role="status" className="mt-1 text-xs text-slate-500">Trwa odczyt ceny.</p>}
    {refresh.isSuccess && result && <p role="status" className="mt-1 break-words text-xs text-emerald-700 dark:text-emerald-300">{result}</p>}
    {refresh.isError && <p role="alert" className="mt-1 break-words text-xs text-amber-800 dark:text-amber-300">{refresh.error.message}</p>}
  </div>
}

function needsAttention(row: PreviewRow): boolean {
  return row.error === true || row.product.consecutive_failures > 0 ||
    row.product.automatic_failures >= 3 ||
    row.product.status === 'UNKNOWN' || row.product.status === 'NOT_FOUND' ||
    (row.history !== undefined && numeric(row.history.stats.current) === null)
}

export function visiblePreviewRows(rows: PreviewRow[], search: string, segment: Segment): PreviewRow[] {
  const term = search.trim().toLocaleLowerCase('pl-PL')
  return rows.filter(row => {
    const product = row.product
    const matchesSearch = `${product.title ?? ''} ${product.asin}`.toLocaleLowerCase('pl-PL').includes(term)
    const matchesSegment = segment === 'all' ||
      (segment === 'drops' && (priceChange(row.history) ?? 0) < 0) ||
      (segment === 'attention' && needsAttention(row)) ||
      (segment === 'paused' && !product.is_active)
    return matchesSearch && matchesSegment
  })
}

export function matchingSuggestions(rows: PreviewRow[], search: string): PreviewRow[] {
  return visiblePreviewRows(rows, search, 'all')
}

export function PreviewDashboard() {
  const client = useQueryClient()
  const products = useQuery({ queryKey: ['products'], queryFn: ({ signal }) => getProducts(signal), refetchInterval: 30_000 })
  const settings = useQuery({ queryKey: ['settings'], queryFn: ({ signal }) => getSettings(signal), retry: false })
  const saveDisplay = useMutation({
    mutationFn: (mode: 'tiles' | 'table') => {
      if (!settings.data) throw new Error('Ustawienia są niedostępne.')
      return updateSettings({
        poll_interval_seconds: settings.data.poll_interval_seconds,
        failed_retry_seconds: settings.data.failed_retry_seconds,
        display_mode: mode,
      })
    },
    onSuccess: updated => client.setQueryData(['settings'], updated),
  })
  const histories = useQueries({ queries: (products.data ?? []).map(product => ({
    queryKey: ['history', product.id, 'PLN'],
    queryFn: ({ signal }: { signal: AbortSignal }) => getHistory(product.id, signal),
    refetchInterval: 30_000,
  })) })
  const rows: PreviewRow[] = (products.data ?? []).map((product, index) => ({
    product, history: histories[index]?.data,
    loading: histories[index]?.isPending, error: histories[index]?.isError,
    retry: () => void histories[index]?.refetch(),
  }))
  return <PreviewLayout rows={rows} loading={products.isPending} error={products.isError}
    retryProducts={() => void products.refetch()}
    displayMode={settings.data?.display_mode ?? 'tiles'} displayModeReady={Boolean(settings.data)}
    displayError={settings.isError || saveDisplay.isError}
    savingDisplay={saveDisplay.isPending}
    onDisplayMode={mode => { saveDisplay.reset(); saveDisplay.mutate(mode) }} />
}

function AddProductForm() {
  const client = useQueryClient()
  const [url, setUrl] = useState('')
  const [validation, setValidation] = useState('')
  const add = useMutation({
    mutationFn: addProduct,
    onSuccess: product => {
      client.setQueryData<Product[]>(['products'], previous =>
        [...(previous ?? []).filter(item => item.id !== product.id), product].sort((a, b) => a.id - b.id))
      setUrl('')
      void client.invalidateQueries({ queryKey: ['products'] })
    },
  })
  const error = validation || (add.isError ? add.error.message : '')
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (add.isPending) return
    add.reset()
    if (!validProductUrl(url)) {
      setValidation('Podaj adres HTTPS amazon.pl/dp/ASIN lub amazon.pl/gp/product/ASIN z 10-znakowym ASIN.')
      return
    }
    setValidation('')
    add.mutate(url)
  }
  return <section className="mt-7 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/40 dark:border-slate-800 dark:bg-slate-900 dark:shadow-none sm:p-6" aria-labelledby="add-product-heading">
    <h2 id="add-product-heading" className="text-xl font-semibold tracking-tight">Dodaj produkt</h2>
    <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Wklej pełny adres produktu z Amazon.pl.</p>
    <form onSubmit={submit} noValidate className="mt-4">
      <label htmlFor="product-url" className="block text-sm font-medium">Adres produktu Amazon.pl</label>
      <div className="mt-1 flex flex-col gap-3 sm:flex-row">
        <input id="product-url" type="url" required value={url} disabled={add.isPending}
          aria-invalid={Boolean(error)} aria-describedby={`url-help${error ? ' url-error' : ''}`}
          onChange={event => { setUrl(event.target.value); setValidation(''); add.reset() }}
          placeholder="https://www.amazon.pl/dp/B012345678"
          className="min-w-0 flex-1 rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm dark:border-slate-700 dark:bg-slate-950" />
        <button type="submit" disabled={add.isPending} className="rounded-xl bg-blue-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:opacity-50">{add.isPending ? 'Dodawanie…' : 'Dodaj do monitorowania'}</button>
      </div>
      <p id="url-help" className="mt-2 text-xs text-slate-500 dark:text-slate-400">Obsługiwane są adresy HTTPS /dp/ i /gp/product/. Krótkie linki nie są obsługiwane.</p>
      {error && <p id="url-error" role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">{error}</p>}
      {add.isSuccess && <p role="status" className="mt-2 text-sm text-emerald-700 dark:text-emerald-300">Produkt dodany. Pierwsze sprawdzenie jest w kolejce.</p>}
    </form>
  </section>
}

function PreviewLayout({ rows, loading = false, error = false, retryProducts,
  displayMode, displayModeReady = false, displayError = false, savingDisplay = false, onDisplayMode,
}: {
  rows: PreviewRow[], loading?: boolean, error?: boolean,
  retryProducts?: () => void, displayMode: 'tiles' | 'table', displayModeReady?: boolean,
  displayError?: boolean, savingDisplay?: boolean, onDisplayMode?: (mode: 'tiles' | 'table') => void,
}) {
  const [search, setSearch] = useState('')
  const [segment, setSegment] = useState<Segment>('all')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [pageSize, setPageSize] = useState(10)
  const [page, setPage] = useState(1)
  const [suggestionsOpen, setSuggestionsOpen] = useState(false)
  const [activeSuggestion, setActiveSuggestion] = useState(0)
  const suggestionList = useRef<HTMLUListElement>(null)
  const visible = visiblePreviewRows(rows, search, segment)
  const pageCount = Math.max(1, Math.ceil(visible.length / pageSize))
  const currentPage = Math.min(page, pageCount)
  const pageRows = visible.slice((currentPage - 1) * pageSize, currentPage * pageSize)
  const selected = pageRows.find(row => row.product.id === selectedId) ?? pageRows[0]
  const suggestions = matchingSuggestions(rows, search)
  useEffect(() => {
    if (suggestionsOpen) suggestionList.current?.children.item(activeSuggestion)?.scrollIntoView({ block: 'nearest' })
  }, [activeSuggestion, suggestionsOpen])
  const updateSearch = (value: string) => {
    setSearch(value)
    setPage(1)
    setSelectedId(null)
    setActiveSuggestion(0)
  }
  const chooseSuggestion = (row: PreviewRow) => {
    updateSearch(row.product.asin)
    setSelectedId(row.product.id)
    setSuggestionsOpen(false)
  }
  const drops = rows.filter(row => (priceChange(row.history) ?? 0) < 0).length
  const attention = rows.filter(needsAttention).length
  const latestCheck = rows.map(row => row.product.last_checked_at).filter((value): value is string => Boolean(value))
    .sort().at(-1) ?? null
  const chips: { key: Segment, label: string }[] = [
    { key: 'all', label: 'Wszystkie' }, { key: 'drops', label: 'Spadek od początku' },
    { key: 'attention', label: 'Wymagają uwagi' }, { key: 'paused', label: 'Wstrzymane' },
  ]
  const points = selected?.history?.snapshots.map(snapshot => ({
    time: utcDate(snapshot.checked_at).getTime(), price: numeric(snapshot.price),
  })) ?? []

  return <main className="min-h-screen bg-slate-50 pb-12 text-slate-950 dark:bg-slate-950 dark:text-slate-100">
    <div className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-8">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-700 text-lg font-bold text-white">↘</div>
          <span className="font-semibold tracking-tight">Monitor cen</span>
        </div>
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <a href="#/settings" className="font-medium underline underline-offset-4">Ustawienia</a>
          <a href="#/info" className="font-medium underline underline-offset-4">Info</a>
          <ThemeToggle />
        </div>
      </div>
    </div>

    <div className="mx-auto max-w-7xl px-4 pt-9 sm:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-700 dark:text-blue-300">Przegląd cen · Amazon.pl</p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight sm:text-4xl">Twoje produkty</h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-300">Ceny pochodzą z zapisanych obserwacji. Brak aktualnej ceny jest pokazany oddzielnie.</p>
        </div>
      </div>

      <dl className="mt-7 grid grid-cols-2 gap-3 xl:grid-cols-4">
        {[
          ['Monitorowane produkty', String(rows.length), 'Wszystkie pozycje na liście'],
          ['Spadek od początku', String(drops), 'Bieżąca cena niższa od pierwszej'],
          ['Wymagają uwagi', String(attention), 'Błąd, brak ceny lub nieznany status'],
          ['Ostatnia próba odczytu', timeLabel(latestCheck), 'Najpóźniejszy czas sprawdzenia produktu'],
        ].map(([label, value, hint]) => <div key={label} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/40 dark:border-slate-800 dark:bg-slate-900 dark:shadow-none">
          <dt className="text-sm text-slate-600 dark:text-slate-300">{label}</dt>
          <dd className={`mt-3 break-words font-semibold tracking-tight tabular-nums ${label === 'Ostatnia próba odczytu' ? 'text-base sm:text-xl' : 'text-2xl'}`}>{value}</dd>
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{hint}</p>
        </div>)}
      </dl>

      <AddProductForm />

      <section className="mt-7 rounded-2xl border border-slate-200 bg-white shadow-sm shadow-slate-200/40 dark:border-slate-800 dark:bg-slate-900 dark:shadow-none" aria-labelledby="preview-list-heading">
        <div className="border-b border-slate-200 p-5 dark:border-slate-800 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div><h2 id="preview-list-heading" className="text-xl font-semibold tracking-tight">Lista produktów</h2>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{visible.length} z {rows.length} produktów</p></div>
            <div className="relative w-full max-w-sm sm:w-72">
              <label htmlFor="preview-search" className="text-sm font-medium">Szukaj nazwy lub ASIN</label>
              <input id="preview-search" type="search" role="combobox" aria-autocomplete="list"
                aria-expanded={suggestionsOpen && suggestions.length > 0} aria-controls="preview-suggestions"
                aria-activedescendant={suggestionsOpen && suggestions.length > 0 ? `preview-suggestion-${suggestions[activeSuggestion]?.product.id}` : undefined}
                value={search} onChange={event => { updateSearch(event.target.value); setSuggestionsOpen(true) }}
                onFocus={() => setSuggestionsOpen(true)}
                onBlur={event => {
                  if (!event.currentTarget.parentElement?.contains(event.relatedTarget as Node)) setSuggestionsOpen(false)
                }}
                onKeyDown={event => {
                  if (event.key === 'Escape') setSuggestionsOpen(false)
                  if (event.key === 'ArrowDown' && suggestions.length > 0) {
                    event.preventDefault()
                    setSuggestionsOpen(true)
                    setActiveSuggestion(index => Math.min(index + 1, suggestions.length - 1))
                  }
                  if (event.key === 'ArrowUp' && suggestions.length > 0) {
                    event.preventDefault()
                    setSuggestionsOpen(true)
                    setActiveSuggestion(index => Math.max(index - 1, 0))
                  }
                  if (event.key === 'Enter' && suggestionsOpen && suggestions.length > 0) {
                    event.preventDefault()
                    chooseSuggestion(suggestions[activeSuggestion])
                  }
                }}
                placeholder="Wpisz nazwę lub ASIN" className="mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm dark:border-slate-700 dark:bg-slate-950" />
              {suggestionsOpen && suggestions.length > 0 && <ul ref={suggestionList} id="preview-suggestions" role="listbox" aria-label="Podpowiedzi produktów"
                className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-xl border border-slate-200 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-900">
                {suggestions.map((row, index) => <li key={row.product.id} id={`preview-suggestion-${row.product.id}`}
                  role="option" aria-selected={index === activeSuggestion}>
                  <button type="button" onMouseDown={event => event.preventDefault()}
                    onClick={() => chooseSuggestion(row)}
                    className={`block w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-100 focus:bg-slate-100 dark:hover:bg-slate-800 dark:focus:bg-slate-800 ${index === activeSuggestion ? 'bg-blue-50 dark:bg-blue-950/40' : ''}`}>
                    <span className="block truncate font-medium">{row.product.title || row.product.asin}</span>
                    <span className="text-xs text-slate-500 dark:text-slate-400">{row.product.asin}</span>
                  </button>
                </li>)}
              </ul>}
            </div>
          </div>
          <div role="group" aria-label="Filtr produktów" className="mt-5 flex flex-wrap gap-2">
            {chips.map(chip => <button key={chip.key} type="button" aria-pressed={segment === chip.key}
              onClick={() => { setSegment(chip.key); setPage(1); setSelectedId(null) }}
              className={`rounded-full px-3.5 py-2 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-700 ${segment === chip.key ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900' : 'bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200'}`}>{chip.label}</button>)}
          </div>
          <div role="group" aria-label="Widok produktów" className="mt-5 flex flex-wrap items-center gap-2 text-sm">
            <span className="mr-1 text-slate-500 dark:text-slate-400">Układ:</span>
            {([['tiles', 'Kafelki'], ['table', 'Tabela']] as const).map(([mode, label]) =>
              <button key={mode} type="button" aria-pressed={displayMode === mode}
                disabled={!displayModeReady || savingDisplay}
                onClick={() => { if (mode !== displayMode) onDisplayMode?.(mode) }}
                className={`rounded-lg px-3 py-1.5 font-medium disabled:opacity-50 ${displayMode === mode ? 'bg-blue-700 text-white' : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200'}`}>{label}</button>)}
          </div>
          {displayError && <p role="alert" className="mt-3 text-sm text-amber-800 dark:text-amber-300">Nie udało się wczytać lub zapisać układu. Pokazano domyślne kafelki.</p>}
        </div>

        {loading && <p role="status" className="p-6 text-sm">Wczytywanie produktów…</p>}
        {error && <p role="alert" className="p-6 text-sm">Nie udało się wczytać listy produktów. {rows.length > 0 && 'Pokazano ostatnio pobrane dane.'}</p>}
        {error && retryProducts && <button type="button" onClick={retryProducts} className="mx-6 mb-5 rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white">Ponów pobieranie produktów</button>}
        {!loading && !error && rows.length === 0 && <p className="p-6 text-sm">Nie ma jeszcze monitorowanych produktów.</p>}
        {rows.length > 0 && visible.length === 0 && <p className="p-6 text-sm">Żaden produkt nie pasuje do wyszukiwania i wybranego widoku.</p>}
        {visible.length > 0 && displayMode === 'tiles' && <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
          {pageRows.map(row => {
            const change = priceChange(row.history)
            return <article key={row.product.id} className="min-w-0 rounded-xl border border-slate-200 p-4 dark:border-slate-700">
              <div className="flex items-start justify-between gap-3">
                <ProductThumbnail key={row.product.image_url} url={row.product.image_url} />
                <h3 title={row.product.title || row.product.asin} className="min-w-0 flex-1 truncate font-semibold">{row.product.title || row.product.asin}</h3>
                <span className="shrink-0 rounded-full bg-slate-100 px-2 py-1 text-xs dark:bg-slate-800">{row.product.queue_state === 'checking' ? 'Sprawdzanie' : row.product.last_checked_at === null ? 'W kolejce' : !row.product.is_active ? 'Wstrzymany' : statusNames[row.product.status]}</span>
              </div>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{row.product.asin}</p>
              <p className="mt-4 text-xl font-bold tabular-nums">{row.loading ? 'Wczytywanie…' : row.history ? displayMoney(row.history.stats.current) : 'Brak danych'}</p>
              <p className={`mt-1 text-sm ${change !== null && change < 0 ? 'text-emerald-700 dark:text-emerald-300' : 'text-slate-500'}`}>Od początku: {change === null ? '—' : displayMoney(row.history?.stats.change_amount)}</p>
              {row.error && <p role="alert" className="mt-2 text-sm text-amber-800 dark:text-amber-300">Nie udało się pobrać historii.</p>}
              {row.product.consecutive_failures > 0 && <p className="mt-2 text-xs text-amber-800 dark:text-amber-300">Ostatnia próba odczytu nie powiodła się.</p>}
              {row.product.pause_reason === 'automatic' && <p className="mt-2 text-xs text-amber-800 dark:text-amber-300">Monitorowanie wstrzymane po dwóch nieudanych ponowieniach. Zaplanowano próbę powrotu.</p>}
              {queueLabel(row.product) && <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{queueLabel(row.product)}</p>}
              <div className="mt-4"><RefreshNowButton product={row.product} /></div>
              <a href={`#/products/${row.product.id}`} className="mt-4 inline-block text-sm font-semibold text-blue-700 underline dark:text-blue-300">Szczegóły i historia →</a>
            </article>
          })}
        </div>}
        {visible.length > 0 && displayMode === 'table' && <div className="grid min-w-0 xl:grid-cols-[minmax(0,1.65fr)_minmax(320px,1fr)]">
          <div className="min-w-0 divide-y divide-slate-100 dark:divide-slate-800 md:hidden">
            {pageRows.map(row => {
              const change = priceChange(row.history)
              const selectedRow = selected?.product.id === row.product.id
              return <div key={row.product.id}>
                <button type="button" aria-pressed={selectedRow}
                onClick={() => setSelectedId(row.product.id)}
                className={`block w-full min-w-0 overflow-hidden p-4 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-700 ${selectedRow ? 'bg-blue-50/70 dark:bg-blue-950/40' : ''}`}>
                <span className="flex min-w-0 items-start gap-3">
                  <ProductThumbnail key={row.product.image_url} url={row.product.image_url} />
                  <span className="min-w-0 flex-1"><span title={row.product.title || row.product.asin} className="line-clamp-2 break-words font-semibold">{row.product.title || row.product.asin}</span><span className="block truncate text-xs text-slate-500 dark:text-slate-400">{row.product.asin}</span></span>
                </span>
                <span className="mt-3 flex min-w-0 flex-wrap items-center justify-between gap-2">
                  <span className={`rounded-full px-2 py-1 text-xs font-medium ${needsAttention(row) ? 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200' : !row.product.is_active ? 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200' : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'}`}>{!row.product.is_active ? 'Wstrzymany' : needsAttention(row) ? 'Sprawdź' : statusNames[row.product.status]}</span>
                  <span className="font-semibold tabular-nums">{row.loading ? 'Wczytywanie…' : row.history ? displayMoney(row.history.stats.current) : 'Brak danych'}</span>
                </span>
                <span className={`mt-2 block text-sm tabular-nums ${change === null ? 'text-slate-500' : change < 0 ? 'text-emerald-700 dark:text-emerald-300' : change > 0 ? 'text-rose-700 dark:text-rose-300' : 'text-slate-500'}`}>Od początku: {change === null ? '—' : `${change < 0 ? '↓ ' : change > 0 ? '↑ ' : ''}${displayMoney(row.history?.stats.change_amount)}`}</span>
                </button>
                <div className="px-4 pb-4"><RefreshNowButton product={row.product} /></div>
              </div>
            })}
          </div>
          <div className="hidden min-w-0 overflow-x-auto md:block">
            <table className="w-full min-w-[700px] table-fixed text-left text-sm">
              <caption className="sr-only">Przegląd zapisanych cen produktów</caption>
              <colgroup><col className="w-[36%]" /><col className="w-[17%]" /><col className="w-[16%]" /><col className="w-[13%]" /><col className="w-[18%]" /></colgroup>
              <thead className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
                <tr><th scope="col" className="py-3 pl-4 pr-1">Produkt</th><th scope="col" className="py-3 pl-1 pr-2 text-right">Cena</th><th scope="col" className="px-2 py-3 text-right">Od początku</th><th scope="col" className="px-2 py-3">Stan</th><th scope="col" className="px-2 py-3">Odczyt</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {pageRows.map(row => {
                  const change = priceChange(row.history)
                  const selectedRow = selected?.product.id === row.product.id
                  return <tr key={row.product.id} tabIndex={0} aria-selected={selectedRow}
                    onClick={() => setSelectedId(row.product.id)}
                    onKeyDown={event => {
                      if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) {
                        event.preventDefault()
                        setSelectedId(row.product.id)
                      }
                    }}
                    className={`cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-700 ${selectedRow ? 'bg-blue-50/70 dark:bg-blue-950/40' : 'hover:bg-slate-50 dark:hover:bg-slate-800/60'}`}>
                    <th scope="row" className="min-w-0 py-4 pl-4 pr-1 font-normal">
                      <span className="flex w-full min-w-0 items-center gap-2 overflow-hidden text-left">
                        <ProductThumbnail key={row.product.image_url} url={row.product.image_url} />
                        <span className="min-w-0 flex-1"><span title={row.product.title || row.product.asin} className="block truncate font-semibold">{row.product.title || row.product.asin}</span><span className="block truncate text-xs text-slate-500 dark:text-slate-400">{row.product.asin}</span></span>
                      </span>
                    </th>
                    <td className="whitespace-nowrap py-4 pl-1 pr-2 text-right font-semibold tabular-nums">{row.loading ? 'Wczytywanie…' : row.history ? displayMoney(row.history.stats.current) : 'Brak danych'}</td>
                    <td className={`whitespace-nowrap px-2 py-4 text-right font-medium tabular-nums ${change === null ? 'text-slate-500' : change < 0 ? 'text-emerald-700 dark:text-emerald-300' : change > 0 ? 'text-rose-700 dark:text-rose-300' : 'text-slate-500'}`}>{change === null ? '—' : `${change < 0 ? '↓ ' : change > 0 ? '↑ ' : ''}${displayMoney(row.history?.stats.change_amount)}`}</td>
                    <td className="px-2 py-4"><span className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ${needsAttention(row) ? 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200' : !row.product.is_active ? 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200' : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'}`}>{!row.product.is_active ? 'Wstrzymany' : needsAttention(row) ? 'Sprawdź' : statusNames[row.product.status]}</span></td>
                    <td className="px-2 py-4"><RefreshNowButton product={row.product} /></td>
                  </tr>
                })}
              </tbody>
            </table>
          </div>

          {selected && <aside className="min-w-0 overflow-hidden border-t border-slate-200 p-5 dark:border-slate-800 sm:p-6 xl:border-l xl:border-t-0" aria-label="Szczegóły wybranego produktu">
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">Wybrany produkt</p>
            <h3 title={selected.product.title || selected.product.asin} className="mt-2 line-clamp-2 break-all text-lg font-semibold">{selected.product.title || selected.product.asin}</h3>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">ASIN {selected.product.asin} · {statusNames[selected.product.status]}</p>
            {selected.error && <p role="alert" className="mt-3 text-sm text-amber-800 dark:text-amber-300">Nie udało się pobrać historii. {selected.history && 'Pokazano ostatnie dane.'}
              <button type="button" onClick={selected.retry} className="ml-2 font-semibold underline">Ponów</button></p>}
            <div className="mt-5 flex flex-wrap items-end justify-between gap-3">
              <div><p className="text-xs text-slate-500 dark:text-slate-400">Bieżąca cena</p><p className="mt-1 text-3xl font-bold tracking-tight tabular-nums">{selected.history ? displayMoney(selected.history.stats.current) : 'Brak danych'}</p></div>
              <div className="text-right"><p className="text-xs text-slate-500 dark:text-slate-400">Minimum w historii</p><p className="mt-1 font-semibold tabular-nums">{displayMoney(selected.history?.stats.minimum)}</p></div>
            </div>
            <div className="mt-6 h-44 w-full min-w-0 overflow-hidden" aria-label="Wykres zapisanych cen">
              {points.some(point => point.price !== null) ? <ResponsiveContainer width="100%" height="100%">
                <LineChart data={points} margin={{ top: 8, right: 8, bottom: 4, left: -16 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#cbd5e1" />
                  <XAxis dataKey="time" type="number" domain={['dataMin', 'dataMax']} tickFormatter={value => new Date(Number(value)).toLocaleDateString('pl-PL', { day: '2-digit', month: '2-digit' })} tick={{ fontSize: 10 }} />
                  <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10 }} />
                  <Tooltip labelFormatter={value => new Date(Number(value)).toLocaleString('pl-PL')} />
                  <Line type="linear" dataKey="price" name="Cena (PLN)" stroke="#2563eb" strokeWidth={2.5} dot={{ r: 2 }} connectNulls={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer> : <p className="pt-10 text-center text-sm text-slate-500">Brak zapisanych cen do wykresu.</p>}
            </div>
            <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">Ostatnia próba odczytu: {timeLabel(selected.product.last_checked_at)}</p>
            {selected.product.consecutive_failures > 0 && <p className="mt-2 text-xs text-amber-800 dark:text-amber-300">Ostatnia próba nie powiodła się; historia może być nieaktualna.</p>}
            {selected.product.pause_reason === 'automatic' && <p className="mt-2 text-xs text-amber-800 dark:text-amber-300">Monitorowanie wstrzymane po dwóch nieudanych ponowieniach. Zaplanowano próbę powrotu.</p>}
            {queueLabel(selected.product) && <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{queueLabel(selected.product)}</p>}
            <a href={`#/products/${selected.product.id}`} className="mt-5 inline-flex rounded-xl bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 dark:bg-blue-600">Otwórz pełną historię →</a>
          </aside>}
        </div>}
        {visible.length > 0 && <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-5 py-4 text-sm dark:border-slate-800 sm:px-6">
          <label className="flex items-center gap-2">Na stronie
            <select aria-label="Liczba produktów na stronie" value={pageSize}
              onChange={event => { setPageSize(Number(event.target.value)); setPage(1); setSelectedId(null) }}
              className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 dark:border-slate-700 dark:bg-slate-950">
              <option value={10}>10</option><option value={20}>20</option>
            </select>
          </label>
          <span className="text-slate-500 dark:text-slate-400">{(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, visible.length)} z {visible.length}</span>
          <nav aria-label="Strony produktów" className="flex items-center gap-2">
            <button type="button" disabled={currentPage === 1} onClick={() => { setPage(currentPage - 1); setSelectedId(null) }}
              className="rounded-lg border border-slate-300 px-3 py-1.5 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700">Wstecz</button>
            <span aria-live="polite">{currentPage} / {pageCount}</span>
            <button type="button" disabled={currentPage === pageCount} onClick={() => { setPage(currentPage + 1); setSelectedId(null) }}
              className="rounded-lg border border-slate-300 px-3 py-1.5 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700">Dalej</button>
          </nav>
        </div>}
      </section>
    </div>
  </main>
}
