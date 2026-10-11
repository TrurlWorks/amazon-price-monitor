import type { ReactNode } from 'react'
import { ThemeToggle } from './theme'

export function PageFrame({ children }: { children: ReactNode }) {
  return <div className="min-h-screen bg-slate-50 pb-12 text-slate-950 dark:bg-slate-950 dark:text-slate-100">
    <div className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-8">
        <a href="#/" className="flex items-center gap-3 font-semibold tracking-tight">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-700 text-lg font-bold text-white">↘</span>
          <span>Monitor cen</span>
        </a>
        <nav aria-label="Główna nawigacja" className="flex flex-wrap items-center gap-4 text-sm">
          <a href="#/" className="font-medium underline underline-offset-4">Produkty</a>
          <a href="#/settings" className="font-medium underline underline-offset-4">Ustawienia</a>
          <a href="#/info" className="font-medium underline underline-offset-4">Info</a>
          <ThemeToggle />
        </nav>
      </div>
    </div>
    {children}
  </div>
}
