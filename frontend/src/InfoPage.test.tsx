import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { Route } from './App'

it('opens the Polish user guide through the info route and shared navigation', () => {
  const html = renderToStaticMarkup(<Route hash="#/info" />)
  for (const text of [
    'href="#/info"', 'href="#/settings"', 'Ciemny motyw',
    'Jak działa Monitor cen', 'Pierwsze kroki', 'Skąd pochodzą dane',
    'Ustawienia', 'Ograniczenia i blokada odczytu przez Amazon',
    'Historia zmian wersji', '0.8.4', '0.8.3', '0.8.2', '0.8.1', '0.8.0', '0.7.0',
    'Sprawdź teraz', 'Blokada Amazon', 'diagnostyce kolejki',
  ]) expect(html).toContain(text)
  expect(html).toContain('id="odczyt"')
  expect(html).toContain('id="ograniczenia"')
  expect(html).not.toContain('Nie znaleziono strony')
})
