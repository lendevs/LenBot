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

export interface PersonaStyle {
  name: string
  /** Share between 0 and 1; all styles add up to 1. */
  weight: number
  note: string | null
}

export interface PersonaExample {
  context: string
  line: string
  tags: string[]
}

/** `PersonaProfile` of panel/routes/persona.py: the parts of the role files the form edits. */
export interface PersonaProfile {
  name: string
  brief: string
  behavior: string
  self_reference: string[]
  aliases: string[]
  styles: PersonaStyle[]
  /** Only examples with one of these tags reach the model; empty means all of them. */
  example_tags: string[]
  voice: string
  boundaries: string
  examples: PersonaExample[]
}

/** Every role write reports which groups use the role and whether they took the change. */
export interface Applied {
  affected_scenes: string[]
  /** False while a group is mid-reply; the change applies when that turn ends. */
  applied?: boolean
  apply_error?: string | null
}

export interface ProfileState extends Applied {
  directory: string
  id: string
  profile: PersonaProfile
}

export const personaFiles = ['persona.yaml', 'voice.md', 'boundaries.md', 'examples.yaml'] as const
export type PersonaFile = (typeof personaFiles)[number]
export type PersonaFiles = Record<PersonaFile, string>
/** The persona's own versions of the framework expression rules; a blank one uses the framework's. */
export const expressionFiles = ['response_choice.md', 'expression_principles.md', 'chat_examples.md'] as const
export type ExpressionFile = (typeof expressionFiles)[number]

export interface KnowledgeListing extends Applied {
  saved_path: string
  files: {
    filename: string
    tags: string[]
    chars: number
    /** Reference index state; only the listing gives it. */
    index?: 'processing' | 'indexed' | 'failed' | null
    chunks?: number | null
    vectors?: number | null
  }[]
  document?: { filename: string; content: string; tags: string[] } | null
}

export interface StickerEntry {
  file: string
  description: string
  emotions: string[]
  tags: string[]
}

export interface StickerListing extends Applied {
  saved_path: string
  files: { file: string; bytes: number }[]
  /** Null until stickers/index.yaml exists. */
  entries: StickerEntry[] | null
}

export interface AvatarState extends Applied {
  directory: string
  saved: { image: unknown }
}

export interface FilesState extends Applied {
  saved: PersonaFiles & Record<ExpressionFile, string>
  saved_path: string
  /** The framework rules a blank expression file falls back to. */
  defaults: Record<ExpressionFile, string>
}

/** What the role adds to the system text in one group, and one style drawn as a turn draws it. */
export interface RolePreview {
  scene: string | null
  sections: { name: 'character' | ExpressionFile; own: boolean; text: string }[]
  examples: number
  styles: { name: string; weight: number; note: string | null }[]
  style: string | null
}

export interface ToolInfo {
  name: string
  description: string
  summary: string
  parameters: unknown
  instructions: string | null
  /** Plugin or MCP server the tool comes from; null for built-in tools. */
  source: string | null
  /** Found through tool_search instead of being listed to the model every turn. */
  deferred: boolean
  /** Why the reference group could not use the tool even when the role allows it. */
  reasons: string[]
}

export interface SkillInfo {
  name: string
  description: string
  source: 'builtin' | 'plugin' | 'shared' | 'scene'
  selected: boolean
}

/** `'all'` allows everything available, including tools and skills added later. */
export type Allowance = 'all' | string[]

export interface Abilities {
  key: string
  directory: string
  /** The group whose configuration the catalog is checked against. */
  scene: string
  affected_scenes: string[]
  tools: { saved: Allowance; catalog: ToolInfo[] }
  skills: { saved: Allowance; directory: string | null; catalog: SkillInfo[] }
}

export interface Trial {
  id: string
  scene: string
  persona: string
  active: boolean
  draft_source: string | null
  memory_plugin: string | null
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

  profile: (key: string, signal?: AbortSignal) =>
    http.get<ProfileState>(`${base(key)}/profile`, undefined, signal),
  saveProfile: (key: string, directory: string, profile: PersonaProfile) =>
    http.put<ProfileState>(`${base(key)}/profile`, { directory, profile }),
  /** Role files of an unsaved form, for a draft trial; nothing is written. */
  draft: (key: string, directory: string, profile: PersonaProfile) =>
    http.post<{ directory: string; files: PersonaFiles; profile: PersonaProfile }>(
      `${base(key)}/profile/draft`,
      {
        directory,
        profile,
      },
    ),

  avatar: (key: string, signal?: AbortSignal) =>
    http.get<AvatarState>(`${base(key)}/avatar`, undefined, signal),
  uploadAvatar: (key: string, directory: string, file: File) => {
    const body = new FormData()
    body.append('file', file)
    body.append('directory', directory)
    return request<AvatarState>(`${base(key)}/avatar`, { method: 'PUT', body })
  },
  removeAvatar: (key: string, directory: string) =>
    http.delete<AvatarState>(`${base(key)}/avatar`, { directory }),
  avatarImage: (key: string, directory: string, version: number) =>
    `${base(key)}/avatar/image?directory=${encodeURIComponent(directory)}&v=${version}`,

  knowledge: (key: string, signal?: AbortSignal) =>
    http.get<KnowledgeListing>(`${base(key)}/knowledge`, undefined, signal),
  document: (key: string, directory: string, filename: string, signal?: AbortSignal) =>
    http.get<{ content: string }>(`${base(key)}/knowledge/document`, { directory, filename }, signal),
  writeDocument: (key: string, creating: boolean, directory: string, filename: string, content: string) =>
    request<KnowledgeListing>(`${base(key)}/knowledge/document`, {
      method: creating ? 'POST' : 'PUT',
      body: { directory, filename, content },
    }),
  removeDocument: (key: string, directory: string, filename: string) =>
    http.delete<KnowledgeListing>(`${base(key)}/knowledge/document`, { directory, filename }),

  stickers: (key: string, signal?: AbortSignal) =>
    http.get<StickerListing>(`${base(key)}/sticker-files`, undefined, signal),
  saveStickers: (key: string, directory: string, entries: StickerEntry[]) =>
    http.put<StickerListing>(`${base(key)}/sticker-files/entries`, { directory, entries }),
  uploadSticker: (key: string, directory: string, file: File) => {
    const body = new FormData()
    body.append('name', file.name)
    body.append('file', file)
    body.append('directory', directory)
    return request<{ file: string }>(`${base(key)}/sticker-files/image`, { method: 'POST', body })
  },
  removeSticker: (key: string, directory: string, file: string) =>
    http.delete<unknown>(`${base(key)}/sticker-files/image`, { directory, file }),
  stickerImage: (key: string, directory: string, file: string) =>
    `${base(key)}/sticker-files/image?file=${encodeURIComponent(file)}&directory=${encodeURIComponent(directory)}`,

  files: (key: string, signal?: AbortSignal) => http.get<FilesState>(`${base(key)}/files`, undefined, signal),
  saveFile: (key: string, directory: string, filename: PersonaFile | ExpressionFile, content: string) =>
    http.put<FilesState>(`${base(key)}/files/${filename}`, { directory, content }),

  /** Without a draft the saved package is previewed. */
  preview: (
    key: string,
    scene: string | null,
    draft: { directory: string; profile: PersonaProfile } | null,
    signal?: AbortSignal,
  ) => request<RolePreview>(`${base(key)}/preview`, { method: 'POST', body: { scene, draft }, signal }),

  abilities: (key: string, signal?: AbortSignal) =>
    http.get<Abilities>(`${base(key)}/abilities`, undefined, signal),
  saveTools: (key: string, directory: string, tools: Allowance) =>
    http.put<Applied & { saved: Allowance }>(`${base(key)}/tools`, { directory, tools }),
  saveSkills: (key: string, directory: string, skills: Allowance) =>
    http.put<Applied & { saved: Allowance }>(`${base(key)}/skills`, { directory, skills }),

  /** A trial of unsaved role files in a copy of one group's settings; platform sending is always simulated. */
  trial: (scene: string, context: number, draft: { directory: string; files: PersonaFiles }) =>
    http.post<Trial>('/api/host/trials', {
      scene,
      acknowledge_model_cost: true,
      context_messages: context,
      persona_draft: draft,
    }),
  stopTrial: (id: string) => http.post<Trial>(`/api/host/trials/${encodeURIComponent(id)}/stop`),
}

/** A new role's folder is also its id: lowercase letters, digits and single hyphens, at most 64. */
export const validFolder = (value: string) => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value) && value.length <= 64

/** The first sentence of a brief, for cards. */
export function firstSentence(text: string | null | undefined): string {
  const value = (text ?? '').trim()
  const end = value.search(/[。！？!?\n]|\.\s/)
  return end === -1 ? value : value.slice(0, end + 1).trim()
}
