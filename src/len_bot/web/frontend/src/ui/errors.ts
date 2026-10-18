import { detailMessage } from '../api/client'

/** The readable message and the raw body of an error thrown by an API call or by the browser. */
export interface DescribedError {
  message: string
  status: number | null
  raw: string | null
}

interface HttpLikeError {
  message?: unknown
  status?: unknown
  detail?: unknown
  details?: unknown
}

function rawText(value: unknown): string | null {
  if (value === undefined || value === null) return null
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/**
 * Accepts both error shapes during the migration: the old api.js Error with `details`, and the new
 * client's ApiError with `detail`. `networkMessage` is shown when the request never reached LenBot.
 */
export function describeError(error: unknown, networkMessage: string): DescribedError {
  if (typeof error === 'string') return { message: error, status: null, raw: null }
  if (error && typeof error === 'object' && (error as { code?: unknown }).code === 'network') {
    return { message: networkMessage, status: null, raw: (error as { message?: string }).message ?? null }
  }
  if (error instanceof TypeError && /fetch|network|load failed/i.test(error.message)) {
    return { message: networkMessage, status: null, raw: error.message }
  }
  if (error && typeof error === 'object') {
    const value = error as HttpLikeError
    const detail = value.detail ?? value.details
    const status = typeof value.status === 'number' ? value.status : null
    const message =
      detailMessage(detail) ??
      (typeof value.message === 'string' && value.message ? value.message : String(error))
    return { message, status, raw: rawText(detail) }
  }
  return { message: String(error), status: null, raw: null }
}
