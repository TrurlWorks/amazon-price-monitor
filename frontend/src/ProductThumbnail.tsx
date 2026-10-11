import { useState } from 'react'

export function ProductThumbnail({ url }: { url: string | null }) {
  const [failed, setFailed] = useState(false)
  if (url && !failed) return <img src={url} alt="" loading="lazy" referrerPolicy="no-referrer"
    onError={() => setFailed(true)}
    className="h-10 w-10 shrink-0 rounded-xl border border-slate-200 bg-white object-contain dark:border-slate-700" />
  return <span aria-hidden="true" className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="8.5" cy="9" r="1.5" />
      <path d="m4 17 5-5 3.5 3.5 2.5-2.5 5 5" />
    </svg>
  </span>
}
