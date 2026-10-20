import { http, request, requestBlob } from './client'
import type { PersonaSummary } from './host'

/** Types of panel/routes/persona.py as the persona library uses them. */

/** `runtime/personas.py` describe(). */
export interface PersonaRole extends PersonaSummary {
  name?: string
  brief?: string | null
  aliases: string[]
  scenes: string[]
  /** Groups running the role right now; differs from `scenes` while a switch waits for a turn. */
  running_scenes: string[]
}

export interface ImportResult {
  /** Set when the package's id was taken and the role got another one. */
  renamed_id?: { from: string; to: string } | null
  [field: string]: unknown
}

const base = (key: string) => `/api/host/personas/${encodeURIComponent(key)}`

export const personasApi = {
  library: (signal?: AbortSignal) =>
    http.get<{ roles: PersonaRole[] }>('/api/host/personas', undefined, signal),
  create: (folder: string, name: string) => http.post<PersonaRole>('/api/host/personas', { folder, name }),
  copy: (key: string, folder: string, name: string) =>
    http.post<PersonaRole>(`${base(key)}/copy`, { folder, name }),
  remove: (key: string) => request<{ moved_to: string }>(base(key), { method: 'DELETE' }),
  importZip: (folder: string, file: File) => {
    const body = new FormData()
    body.append('name', folder)
    body.append('file', file)
    return request<ImportResult>('/api/host/personas/import', { method: 'POST', body })
  },
  package: (key: string) => requestBlob(`${base(key)}/package`),
}

/** A new role's folder is also its id: lowercase letters, digits and single hyphens, at most 64. */
export const validFolder = (value: string) => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value) && value.length <= 64

/** The first sentence of a brief, for cards. */
export function firstSentence(text: string | null | undefined): string {
  const value = (text ?? '').trim()
  const end = value.search(/[。！？!?\n]|\.\s/)
  return end === -1 ? value : value.slice(0, end + 1).trim()
}
