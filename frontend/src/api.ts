export interface Health {
  status: 'ok'
  database: 'ok'
}

export async function getHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch('/api/health', { signal })
  if (!response.ok) throw new Error('Service unavailable')
  const body: unknown = await response.json()
  if (
    typeof body !== 'object' ||
    body === null ||
    !('status' in body) || body.status !== 'ok' ||
    !('database' in body) || body.database !== 'ok'
  ) {
    throw new Error('Invalid health response')
  }
  return { status: 'ok', database: 'ok' }
}
