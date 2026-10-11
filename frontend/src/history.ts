import { utcDate, type Snapshot } from './products'

export const ranges = ['24h', '7d', '30d', '90d', 'ALL'] as const
export type HistoryRange = typeof ranges[number]
const durations = {
  '24h': 86_400_000,
  '7d': 7 * 86_400_000,
  '30d': 30 * 86_400_000,
  '90d': 90 * 86_400_000,
}

export function historyWindow(snapshots: Snapshot[], range: HistoryRange, now: number) {
  const ordered = [...snapshots].sort((a, b) =>
    utcDate(a.checked_at).getTime() - utcDate(b.checked_at).getTime() || a.id - b.id)
  if (range === 'ALL') return ordered
  return ordered.filter(snapshot => {
    const time = utcDate(snapshot.checked_at).getTime()
    return time >= now - durations[range] && time <= now
  })
}

export const historyTimestamp = (value: string | null) =>
  value ? utcDate(value).toLocaleString('pl-PL') : 'Jeszcze nie sprawdzono'
