/**
 * The one HTTP client of the new panel: same-origin credentials, JSON or binary bodies, ApiError with the
 * status and the server's detail, one handler for 401, and results from before a login change dropped.
 * The old api.js shares the session counter and the 401 handler until it is removed (work.md M4.9).
 */

export type Query = Record<string, string | number | boolean | null | undefined>

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  /** Plain values are sent as JSON; FormData and Blob are sent as they are. */
  body?: unknown
  query?: Query
  signal?: AbortSignal
  headers?: Record<string, string>
}

export class ApiError extends Error {
  /** HTTP status; 0 when the request never got an answer. */
  readonly status: number
  /** The `detail` field of the error body, kept as sent: `{message, code, data?}`. */
  readonly detail: unknown
  readonly code: string | null
  /** `detail.data`: what a page needs to recover from this error, such as the latest snapshot on a conflict. */
  readonly data: unknown

  constructor(message: string, status: number, detail: unknown = null, code: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.code = code
    this.data = detail && typeof detail === 'object' ? ((detail as { data?: unknown }).data ?? null) : null
  }
}

/** A request answered after the login changed; its result belongs to the previous user and is dropped. */
export class SessionChangedError extends ApiError {
  constructor(status: number) {
    super('Session changed', status, null, 'session_changed')
    this.name = 'SessionChangedError'
  }
}

let generation = 0
let unauthorized: () => void = () => {}

export function currentSession(): number {
  return generation
}

/** Called on login and logout. */
export function resetSession(): void {
  generation += 1
}

export function onUnauthorized(handler: () => void): void {
  unauthorized = handler
}

/** Readable text of an error `detail`: `{message}`, or a plain string or validation list from older answers. */
export function detailMessage(detail: unknown): string | null {
  if (typeof detail === 'string') return detail || null
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      const entry = item as { loc?: unknown[]; msg?: unknown }
      const where = Array.isArray(entry.loc) ? entry.loc.join('.') : ''
      const text = typeof entry.msg === 'string' ? entry.msg : JSON.stringify(item)
      return where ? `${where}: ${text}` : text
    })
    return parts.join('；') || null
  }
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message
    if (typeof message === 'string') return message
  }
  return null
}

export function queryString(query: Query = {}): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const session = generation
  const headers: Record<string, string> = { ...options.headers }
  let body: BodyInit | undefined
  if (options.body instanceof FormData || options.body instanceof Blob) body = options.body
  else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  let response: Response
  try {
    response = await fetch(path + queryString(options.query), {
      method: options.method ?? (body === undefined ? 'GET' : 'POST'),
      headers,
      body,
      signal: options.signal,
      credentials: 'same-origin',
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(error instanceof Error ? error.message : String(error), 0, null, 'network')
  }
  if (response.status === 401 && path !== '/api/auth/login' && session === generation) unauthorized()
  if (session !== generation) throw new SessionChangedError(response.status)
  if (!response.ok) {
    let detail: unknown = null
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail ?? null
    } catch {
      detail = null
    }
    const code = detail && typeof detail === 'object' ? (detail as { code?: unknown }).code : null
    throw new ApiError(
      detailMessage(detail) ?? `HTTP ${response.status}`,
      response.status,
      detail,
      typeof code === 'string' ? code : null,
    )
  }
  return response
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options)
  if (response.status === 204) return undefined as T
  try {
    return (await response.json()) as T
  } catch (error) {
    throw new ApiError(
      `HTTP ${response.status}: ${error instanceof Error ? error.message : String(error)}`,
      response.status,
      null,
      'invalid_json',
    )
  }
}

export async function requestBlob(path: string, options: RequestOptions = {}): Promise<Blob> {
  return (await send(path, options)).blob()
}

export const http = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>(path, { query, signal }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  delete: <T>(path: string, body?: unknown) => request<T>(path, { method: 'DELETE', body }),
}

/** WebSocket URL on the panel's own origin. */
export function socketUrl(path: string): string {
  return `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${path}`
}
