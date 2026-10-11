import { PageFrame } from './PageFrame'

const section = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/40 dark:border-slate-800 dark:bg-slate-900 dark:shadow-none sm:p-7'
const link = 'font-medium text-blue-700 underline underline-offset-4 dark:text-blue-300'

const releases = [
  { version: '0.8.4', changes: 'Zwężono tabelę produktów; kliknięcie dowolnego miejsca wiersza wybiera produkt, a przycisk „Sprawdź teraz” nadal wykonuje odczyt.' },
  { version: '0.8.3', changes: 'Dodano bezpośrednie sprawdzanie cen w kafelkach i tabeli oraz wynik odczytu przy produkcie.' },
  { version: '0.8.2', changes: 'Dodano tę instrukcję użytkownika i odnośnik Info w nawigacji.' },
  { version: '0.8.1', changes: 'Poprawiono czytelność kolejki, dodano szacowany plan odczytów i bezpośredni przycisk „Sprawdź teraz”.' },
  { version: '0.8.0', changes: 'Dodano diagnostykę kolejki, historię prób i jednorazową zmianę terminu najbliższego odczytu.' },
  { version: '0.7.0', changes: 'Wprowadzono trwałą kolejkę automatycznych odczytów, odstępy między nimi i próby powrotu po błędach.' },
] as const

export function InfoPage() {
  return <PageFrame><main className="mx-auto max-w-5xl px-4 py-9 sm:px-8">
    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-700 dark:text-blue-300">Pomoc · Amazon.pl</p>
    <h1 className="mt-2 text-3xl font-bold tracking-tight sm:text-4xl">Jak działa Monitor cen</h1>
    <p className="mt-3 max-w-3xl text-slate-600 dark:text-slate-300">Aplikacja zapisuje kolejne odczyty cen wybranych produktów Amazon.pl i pokazuje ich historię. Poniżej znajdziesz krótką instrukcję, opis ustawień i ograniczenia odczytu.</p>

    <nav aria-label="Spis treści instrukcji" className="mt-7 flex flex-wrap gap-2 text-sm">
      {([
        ['start', 'Pierwsze kroki'], ['odczyt', 'Odczyt cen'], ['ustawienia', 'Ustawienia'],
        ['ograniczenia', 'Ograniczenia'], ['wersje', 'Historia zmian'],
      ] as const).map(([id, label]) =>
        <button key={id} type="button" onClick={() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })}
          className="rounded-full border border-slate-200 bg-white px-3 py-2 font-medium text-slate-700 hover:border-blue-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">{label}</button>)}
    </nav>

    <div className="mt-7 grid gap-5">
      <section id="start" aria-labelledby="start-heading" className={section}>
        <h2 id="start-heading" className="text-xl font-bold">Pierwsze kroki</h2>
        <ol className="mt-4 list-decimal space-y-3 pl-5 text-sm leading-6 text-slate-700 dark:text-slate-300">
          <li>Na stronie <a href="#/" className={link}>Produkty</a> wklej adres produktu Amazon.pl w formacie <span className="break-all font-mono">https://www.amazon.pl/dp/ASIN</span> i dodaj go do monitorowania. ASIN to 10 znaków identyfikujących produkt.</li>
          <li>Produkt pojawi się na liście od razu. Pierwsza cena pojawi się po odczycie wykonanym przez kolejkę; do tego czasu zobaczysz „Brak ceny”.</li>
          <li>Wyszukuj po nazwie lub ASIN, wybierz liczbę produktów na stronie i przełącz układ „Kafelki” lub „Tabela”. Filtr „Wymagają uwagi” pokazuje między innymi produkty z błędem odczytu.</li>
          <li>Użyj „Sprawdź teraz” przy produkcie w kafelkach lub tabeli, aby odczytać cenę bez czekania w kolejce. Po próbie zobaczysz wynik odczytu. Otwórz szczegóły produktu, aby zobaczyć wykres i historię cen, wstrzymać monitorowanie albo usunąć produkt wraz z historią.</li>
        </ol>
      </section>

      <section id="odczyt" aria-labelledby="odczyt-heading" className={section}>
        <h2 id="odczyt-heading" className="text-xl font-bold">Skąd pochodzą dane</h2>
        <p className="mt-4 text-sm leading-6 text-slate-700 dark:text-slate-300">W zwykłym trybie aplikacja pobiera po stronie serwera publiczną stronę produktu Amazon.pl pod kanonicznym adresem produktu. Odczytuje widoczną nazwę, zdjęcie, cenę w PLN, dostępność i sprzedawcę, jeśli te dane są rozpoznawalne. Nie korzysta z ceny wpisanej przez użytkownika ani z historii prezentowanej przez Amazon.</p>
        <p className="mt-3 text-sm leading-6 text-slate-700 dark:text-slate-300">Udany odczyt zapisuje nową obserwację, także gdy cena się nie zmieniła. Nieudany odczyt zapisuje wynik próby diagnostycznej, ale nie dopisuje ceny ani nie zastępuje ostatniej poprawnej obserwacji. Pusta cena może oznaczać, że strona została rozpoznana, lecz nie zawierała obsługiwanej ceny.</p>
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl bg-slate-50 p-4 dark:bg-slate-800/60"><h3 className="font-semibold">Automatycznie</h3><p className="mt-2 text-sm leading-6">Produkty trafiają do trwałej kolejki. Jeden worker sprawdza je kolejno, zachowując wspólny odstęp. Po błędzie wykonuje najwyżej dwa ponowienia; potem produkt wymaga uwagi i czeka na rzadszą próbę powrotu.</p></div>
          <div className="rounded-xl bg-slate-50 p-4 dark:bg-slate-800/60"><h3 className="font-semibold">Na żądanie</h3><p className="mt-2 text-sm leading-6">Przycisk „Sprawdź teraz” na liście i w szczegółach uruchamia pojedynczy odczyt bezpośrednio. Działa także dla produktu ręcznie wstrzymanego. Na liście zobaczysz, czy ostatnia próba zapisała cenę. Gdy cena nie została odczytana, poprzednia poprawna cena może nadal być widoczna jako bieżąca.</p></div>
        </div>
        <p className="mt-4 text-sm leading-6 text-slate-700 dark:text-slate-300">W <a href="#/settings/queue" className={link}>diagnostyce kolejki</a> zobaczysz zadany termin, szacowany plan startu i wyniki prób. Plan jest prognozą: nowe zlecenia, czas pobierania i przerwy po blokadach mogą go przesunąć. Możesz jednorazowo zmienić termin najbliższej próby produktu.</p>
      </section>

      <section id="ustawienia" aria-labelledby="settings-heading" className={section}>
        <h2 id="settings-heading" className="text-xl font-bold">Ustawienia</h2>
        <dl className="mt-4 grid gap-4 text-sm leading-6 sm:grid-cols-2">
          <div><dt className="font-semibold">Odstęp między sprawdzeniami (godziny)</dt><dd className="text-slate-600 dark:text-slate-300">Jak często produkt ma otrzymywać regularny termin odczytu. To nie jest odstęp między kolejnymi żądaniami całej aplikacji.</dd></div>
          <div><dt className="font-semibold">Ponowna próba po błędzie (minuty)</dt><dd className="text-slate-600 dark:text-slate-300">Podstawa odstępu dla automatycznych ponowień po nieudanym odczycie. Druga próba czeka dłużej.</dd></div>
          <div><dt className="font-semibold">Widok produktów</dt><dd className="text-slate-600 dark:text-slate-300">Wybór między kafelkami a tabelą. Jest zapisywany i pozostaje po ponownym otwarciu strony.</dd></div>
          <div><dt className="font-semibold">Motyw</dt><dd className="text-slate-600 dark:text-slate-300">Przycisk „Jasny motyw” lub „Ciemny motyw” w nagłówku zapamiętuje wybór w tej przeglądarce.</dd></div>
          <div><dt className="font-semibold">Globalna przerwa</dt><dd className="text-slate-600 dark:text-slate-300">Wspólny odstęp między automatycznymi startami jest ustawiany na serwerze; domyślnie wynosi 3 minuty. Nie zmienia się go w formularzu ustawień.</dd></div>
          <div><dt className="font-semibold">Informacje o stanie</dt><dd className="text-slate-600 dark:text-slate-300">Wersja, źródło danych i liczniki pomagają sprawdzić konfigurację. „Stan API” nie potwierdza, że Amazon odpowiada poprawnie.</dd></div>
        </dl>
        <a href="#/settings" className={`${link} mt-5 inline-block`}>Otwórz Ustawienia →</a>
      </section>

      <section id="ograniczenia" aria-labelledby="limits-heading" className={section}>
        <h2 id="limits-heading" className="text-xl font-bold">Ograniczenia i blokada odczytu przez Amazon</h2>
        <ul className="mt-4 list-disc space-y-3 pl-5 text-sm leading-6 text-slate-700 dark:text-slate-300">
          <li>Amazon może zwrócić stronę weryfikacyjną lub odmówić dostępu. Rozpoznana strona weryfikacyjna ma wynik „Blokada Amazon”; inne nieudane odpowiedzi mogą mieć wynik „Błąd”. W obu przypadkach poprzednia poprawna cena pozostaje bez zmian. Samo wejście na stronę produktu w przeglądarce nie dowodzi, że serwer aplikacji otrzyma tę samą odpowiedź.</li>
          <li>Gdy w ciągu godziny strony weryfikacyjne dotyczą dwóch różnych produktów, kolejka robi wspólną przerwę i później podejmuje próbę kontrolną. Produkt po powtarzających się błędach trafia do „Wymagających uwagi” i ma rzadsze próby powrotu. Nie znamy bezpiecznego limitu żądań Amazon; ta ochrona nie gwarantuje odczytu.</li>
          <li>„Sprawdź teraz” uruchamia odczyt bez czekania na kolejkę, także podczas jej przerwy. Powtarzanie go wiele razy może zwiększyć ryzyko kolejnej blokady. Aplikacja nie rozwiązuje CAPTCHA i nie obchodzi ograniczeń serwisu.</li>
          <li>Widoczna cena może zależeć od sprzedawcy, dostępności, promocji, dostawy lub personalizacji. Aplikacja zapisuje rozpoznaną cenę ze strony produktu, nie oblicza kuponów i kosztów dostawy. Zmiana struktury strony może uniemożliwić odczyt.</li>
          <li>Aplikacja nie wysyła powiadomień. Nie ma też logowania ani szyfrowania połączenia HTTPS w obecnej konfiguracji; używaj jej wyłącznie w zaufanej sieci.</li>
        </ul>
      </section>

      <section id="wersje" aria-labelledby="versions-heading" className={section}>
        <h2 id="versions-heading" className="text-xl font-bold">Historia zmian wersji</h2>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">Poniżej są opisane wersje z udokumentowanymi zmianami od 0.7.0. Numer wersji jest też widoczny w Ustawieniach.</p>
        <ol className="mt-5 space-y-4">{releases.map(release =>
          <li key={release.version} className="grid gap-1 border-l-2 border-blue-200 pl-4 text-sm leading-6 dark:border-blue-900 sm:grid-cols-[5rem_1fr] sm:gap-4">
            <strong className="text-blue-800 dark:text-blue-300">{release.version}</strong>
            <span className="text-slate-700 dark:text-slate-300">{release.changes}</span>
          </li>)}</ol>
      </section>
    </div>
  </main></PageFrame>
}
