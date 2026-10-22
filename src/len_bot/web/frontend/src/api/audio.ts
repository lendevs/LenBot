import { http } from './client'

/** Types of panel/routes/audio.py. */

export type AudioStatus = 'idle' | 'queued' | 'running' | 'complete' | 'failed' | 'interrupted'

/** `media/audio_store.py` items(): one voice message part. */
export interface AudioItem {
  platform_id: string
  audio_index: number
  duration: number | null
  transcript: string | null
  status: AudioStatus
  updated: number
  error: string | null
  /** Null when the recording is not cached. */
  wav_bytes: number | null
  [field: string]: unknown
}

export interface AudioPage {
  items: AudioItem[]
  next_offset: number | null
  automatic: boolean
  timezone: string
  /** False without a speech recognition model or platform connection. */
  available: boolean
  worker_error: string | null
  stopping: boolean
}

const root = (scene: string) => `/api/host/scenes/${encodeURIComponent(scene)}/audio`
const itemPath = (scene: string, item: AudioItem) =>
  `${root(scene)}/${encodeURIComponent(item.platform_id)}/${item.audio_index}`

export const audioApi = {
  list: (scene: string, offset: number, signal?: AbortSignal) =>
    http.get<AudioPage>(root(scene), { offset }, signal),
  wavUrl: (scene: string, item: AudioItem) => `${itemPath(scene, item)}/wav`,
  calls: (scene: string, item: AudioItem) => http.get<unknown>(`${itemPath(scene, item)}/calls`),
  transcribe: (scene: string, item: AudioItem) =>
    http.post<unknown>(`${itemPath(scene, item)}/transcribe`, { refresh: item.wav_bytes !== null }),
}
