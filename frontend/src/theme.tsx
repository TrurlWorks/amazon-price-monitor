import { useState } from 'react'

export type Theme = 'light' | 'dark'

export function initialTheme(): Theme {
  if (typeof document === 'undefined') return 'light'
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light'
}

export function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  try {
    window.localStorage.setItem('theme', theme)
  } catch {
    // Keep the toggle usable when storage is unavailable.
  }
}

export function ThemeToggle() {
  const [theme, setTheme] = useState(initialTheme)
  function toggle() {
    const next = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    setTheme(next)
  }
  return <button
    type="button"
    aria-pressed={theme === 'dark'}
    onClick={toggle}
    className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 dark:border-slate-700 dark:text-slate-200"
  >
    {theme === 'dark' ? 'Jasny motyw' : 'Ciemny motyw'}
  </button>
}
