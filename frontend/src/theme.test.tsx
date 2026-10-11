import { afterEach, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import html from '../index.html?raw'
import { applyTheme, initialTheme, ThemeToggle } from './theme'

afterEach(() => vi.unstubAllGlobals())

function browser(stored: string | null, prefersDark: boolean, blocked = false) {
  const classes = new Set(['existing'])
  const storage = {
    getItem: vi.fn(() => {
      if (blocked) throw new Error('Storage blocked')
      return stored
    }),
    setItem: vi.fn((_key: string, value: string) => {
      if (blocked) throw new Error('Storage blocked')
      stored = value
    }),
  }
  const document = {
    documentElement: {
      classList: {
        contains: (name: string) => classes.has(name),
        toggle: (name: string, enabled: boolean) => {
          if (enabled) classes.add(name)
          else classes.delete(name)
        },
      },
    },
  }
  const window = {
    localStorage: storage,
    matchMedia: vi.fn(() => ({ matches: prefersDark })),
  }
  vi.stubGlobal('document', document)
  vi.stubGlobal('window', window)
  const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1]
  if (!script) throw new Error('Missing initial theme script')
  const boot = () => new Function('window', 'document', 'localStorage', script)(
    window, document, storage,
  )
  return { classes, storage, boot }
}

it.each([
  ['dark', false, 'dark'],
  ['light', true, 'light'],
  [null, true, 'dark'],
  [null, false, 'light'],
  ['invalid', true, 'dark'],
] as const)('initializes %s with system dark=%s as %s', (stored, system, expected) => {
  const { boot, classes, storage } = browser(stored, system)
  boot()
  expect(initialTheme()).toBe(expected)
  expect(classes.has('existing')).toBe(true)
  expect(storage.setItem).not.toHaveBeenCalled()
})

it('places initialization before the root and React entry', () => {
  expect(html.indexOf('<script>')).toBeLessThan(html.indexOf('<div id="root">'))
  expect(html.indexOf('<script>')).toBeLessThan(html.indexOf('src="/src/main.tsx"'))
})

it('persists both choices across initialization and exposes their pressed state', () => {
  const { boot, storage } = browser(null, false)
  boot()
  for (const theme of ['dark', 'light'] as const) {
    applyTheme(theme)
    expect(storage.setItem).toHaveBeenLastCalledWith('theme', theme)
    boot()
    expect(initialTheme()).toBe(theme)
    const markup = renderToStaticMarkup(<ThemeToggle />)
    expect(markup).toContain('type="button"')
    expect(markup).toContain(`aria-pressed="${theme === 'dark'}"`)
    expect(markup).toContain(theme === 'dark' ? '>Jasny motyw</button>' : '>Ciemny motyw</button>')
  }
})

it('uses system preference and remains usable when storage throws', () => {
  const { boot, classes } = browser(null, true, true)
  expect(boot).not.toThrow()
  expect(initialTheme()).toBe('dark')
  expect(() => applyTheme('light')).not.toThrow()
  expect(classes.has('dark')).toBe(false)
  expect(initialTheme()).toBe('light')
})
