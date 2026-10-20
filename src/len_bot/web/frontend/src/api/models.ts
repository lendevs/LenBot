import { http } from './client'

/** Types of the model helpers in panel/routes/settings.py. */

/** One saved provider as GET /api/host/settings shows it; the key itself is never sent back. */
export interface SavedProvider {
  api: string
  base_url: string
  api_key_configured: boolean
  proxy: string | null
}

export interface EmbeddingBinding {
  provider: string
  model: string
  dimensions: number | null
}

export interface ListedModel {
  id: string
  name: string
}

export interface ProbeResult {
  model?: string
  kind: 'text' | 'tools' | 'embedding'
  text: string
  usage?: unknown
}

/** A saved provider as a request candidate: the host fills in its stored key by alias. */
const candidate = (alias: string, provider: SavedProvider) => ({
  alias,
  provider: {
    api: provider.api,
    base_url: provider.base_url.replace(/\/+$/, ''),
    api_key: null,
    proxy: provider.proxy || null,
  },
})

export const modelsApi = {
  list: (alias: string, provider: SavedProvider) =>
    http.post<{ models: ListedModel[] }>('/api/host/models/list', candidate(alias, provider)),
  probeEmbedding: (alias: string, provider: SavedProvider, binding: EmbeddingBinding) =>
    http.post<ProbeResult>('/api/host/models/probe', {
      ...candidate(alias, provider),
      binding,
      kind: 'embedding',
    }),
}
