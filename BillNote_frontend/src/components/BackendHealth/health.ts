export type BackendHealthResult = 'ok' | 'degraded' | 'unreachable'

export function readBackendHealth(body: unknown): BackendHealthResult {
  const response = body as { code?: number; data?: { backend?: string; ffmpeg?: string; db?: string } } | null
  if (response?.code !== 0 || response.data?.backend !== 'ok') return 'unreachable'
  return response.data.ffmpeg === 'ok' && response.data.db === 'ok' ? 'ok' : 'degraded'
}
