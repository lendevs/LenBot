import { http, request } from './client'

/** Types of panel/routes/reference.py. */

export type ReferenceStatus = 'processing' | 'indexed' | 'failed'

export interface ReferenceFile {
  filename: string
  kind: 'markdown' | 'text' | 'pdf' | string
  size: number
  /** Seconds since the epoch. */
  modified: number
  status: ReferenceStatus
  error: string | null
  chars: number | null
  pages: number | null
  chunks: number
  vectors: number
}

/** GET /api/host/scenes/{scene}/reference */
export interface ReferenceListing {
  scene: string
  files: ReferenceFile[]
  processing: boolean
  /** Whether memory embeddings are configured, so chunks also get vectors. */
  vectors: boolean
  formats: string[]
  max_bytes: number
  /** Whether this chat is a OneBot group, so files can be picked from its group files. */
  group_files: boolean
}

export interface GroupFile {
  file_id: string
  busid: number
  name: string
  size: number
  /** Seconds since the epoch. */
  uploaded: number
  uploader: string | null
  /** A supported format within the size limit. */
  supported: boolean
}

export interface GroupFolder {
  folder_id: string
  name: string
  files: number
}

/** GET /api/host/scenes/{scene}/reference/group-files */
export interface GroupFiles {
  /** null for the root. */
  folder: string | null
  files: GroupFile[]
  folders: GroupFolder[]
}

const base = (scene: string) => `/api/host/scenes/${encodeURIComponent(scene)}/reference`

export const referenceApi = {
  listing: (scene: string, signal?: AbortSignal) =>
    http.get<ReferenceListing>(base(scene), undefined, signal),
  upload: (scene: string, file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<ReferenceListing>(base(scene), { method: 'POST', body })
  },
  remove: (scene: string, filename: string) => http.delete<ReferenceListing>(base(scene), { filename }),
  reprocess: (scene: string, filename: string) =>
    http.post<ReferenceListing>(`${base(scene)}/reprocess`, { filename }),
  groupFiles: (scene: string, folder: string | null, signal?: AbortSignal) =>
    http.get<GroupFiles>(`${base(scene)}/group-files`, folder === null ? undefined : { folder }, signal),
  importGroupFile: (scene: string, file: GroupFile) =>
    http.post<ReferenceListing>(`${base(scene)}/group-files`, {
      file_id: file.file_id,
      busid: file.busid,
      name: file.name,
    }),
}
