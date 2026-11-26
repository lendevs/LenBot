import { computed, inject, reactive, ref, watch, type InjectionKey } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import type { WebRead, WebSearch } from '../../api/capabilities'
import {
  modelsApi,
  trimUrl,
  type AsrBinding,
  type Candidate,
  type ChatBinding,
  type ChatRole,
  type EmbeddingBinding,
  type ListedModel,
  type ModelRoles,
  type ModelsChange,
  type SavedProvider,
} from '../../api/models'
import { keys } from '../../api/query'
import { settingsApi, type SettingsSnapshot } from '../../api/settings'
import { READ_APIS, SEARCH_APIS } from '../../api/webServices'
import { readPendingRestart } from '../../api/hostStore'
import { groupLabel } from '../../layouts/shell/scenes'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

/** A provider in the form. Bindings point at `id`, so renaming a provider keeps its users. */
export interface ProviderRow {
  id: string
  alias: string
  /** The saved name; null for a provider added in this form. */
  originalAlias: string | null
  api: string
  base_url: string
  /** Typed in this form; empty keeps the saved key when it still applies. */
  api_key: string
  proxy: string
  keyConfigured: boolean
  /** Protocol, address and proxy the saved key belongs to. */
  keyFor: string | null
}

export interface ModelsDraft {
  providers: ProviderRow[]
  roles: ModelRoles
  memory_embedding: EmbeddingBinding | null
  learning_embeddings: Record<string, EmbeddingBinding | null>
}

export const chatRoles: ChatRole[] = ['mind', 'vision', 'memory', 'learner', 'worker']

/** The saved key is only reused for the same protocol, address and proxy. */
const credentials = (row: { api: string; base_url: string; proxy: string | null }) =>
  JSON.stringify([row.api, trimUrl(row.base_url), trimUrl(row.proxy)])
export const keyReusable = (row: ProviderRow) => row.keyConfigured && row.keyFor === credentials(row)
export const hasKey = (row: ProviderRow) => keyReusable(row) || Boolean(row.api_key.trim())

export const candidateOf = (row: ProviderRow): Candidate => ({
  alias: row.originalAlias,
  provider: {
    api: row.api,
    base_url: trimUrl(row.base_url),
    api_key: row.api_key.trim() || null,
    proxy: trimUrl(row.proxy) || null,
  },
})

export function newBinding(
  provider: string,
  role?: Exclude<ChatRole, 'mind'>,
  mind?: ChatBinding,
): ChatBinding {
  const contextWindow = mind?.context_window_tokens ?? 128000
  const baseMaxOutput = role === 'worker' ? Math.max(4096, mind?.max_output_tokens ?? 4096) : 4096
  return {
    provider,
    model: '',
    context_window_tokens: contextWindow,
    temperature: null,
    max_output_tokens: Math.min(baseMaxOutput, Math.max(1, contextWindow - 1)),
    timeout_seconds: role === 'worker' || role === 'memory' ? 180 : 60,
    thinking: null,
    reasoning_effort: null,
    quick_reasoning_effort: null,
    thinking_budget_tokens: null,
    image_input: role === 'vision',
    anti_bagu: false,
    output_token_field: 'max_completion_tokens',
    history_policy: 'native',
    retry_delays_seconds: [2, 5],
  }
}

export const isDeepSeekModel = (model: string | null | undefined, baseUrl?: string | null): boolean =>
  /deepseek/i.test(model ?? '') || /deepseek/i.test(baseUrl ?? '')

/** Protocol-specific fields the host refuses for other protocols. */
export function fitProtocol(binding: ChatBinding, api: string | undefined) {
  if (api !== 'openai-chat') {
    binding.thinking = null
    binding.history_policy = 'native'
    binding.output_token_field = 'max_completion_tokens'
  }
  if (api !== 'anthropic' && api !== 'gemini') binding.thinking_budget_tokens = null
}

interface SavedModels {
  providers: Record<string, SavedProvider>
  roles: ModelRoles
}
interface SavedScene {
  learning: { embedding: EmbeddingBinding | null } | null
}

const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T

function fromSnapshot(snapshot: SettingsSnapshot): ModelsDraft {
  const models = snapshot.saved.models as SavedModels
  const memory = snapshot.saved.memory as { local: { embedding: EmbeddingBinding | null } } | null
  const scenes = snapshot.saved.scenes as unknown as Record<string, SavedScene>
  return {
    providers: Object.entries(models.providers).map(([alias, item]) => ({
      id: alias,
      alias,
      originalAlias: alias,
      api: item.api,
      base_url: item.base_url,
      api_key: '',
      proxy: item.proxy ?? '',
      keyConfigured: item.api_key_configured,
      keyFor: credentials(item),
    })),
    roles: copy(models.roles),
    memory_embedding: copy(memory?.local.embedding ?? null),
    learning_embeddings: Object.fromEntries(
      Object.entries(scenes)
        .filter(([, scene]) => scene.learning !== null)
        .map(([scene, value]) => [scene, copy(value.learning!.embedding)]),
    ),
  }
}

function toChange(draft: ModelsDraft, memory: boolean): ModelsChange {
  const alias = (id: string) => draft.providers.find((row) => row.id === id)?.alias ?? id
  const bind = <T extends { provider: string }>(item: T | null): T | null =>
    item === null ? null : { ...item, provider: alias(item.provider) }
  return {
    providers: Object.fromEntries(
      draft.providers.map((row) => [
        row.alias,
        {
          previous_alias: row.originalAlias,
          api: row.api,
          base_url: trimUrl(row.base_url),
          api_key: row.api_key.trim() || null,
          proxy: trimUrl(row.proxy) || null,
        },
      ]),
    ),
    roles: Object.fromEntries(
      Object.entries(draft.roles).map(([role, item]) => [
        role,
        bind(item as ChatBinding | AsrBinding | null),
      ]),
    ) as ModelRoles,
    ...(memory ? { memory_embedding: bind(draft.memory_embedding) } : {}),
    learning_embeddings: Object.fromEntries(
      Object.entries(draft.learning_embeddings).map(([scene, item]) => [scene, bind(item)]),
    ),
  }
}

export type Tab = 'providers' | 'roles' | 'vectors' | 'usage'
export type ProblemField =
  | 'name'
  | 'url'
  | 'key'
  | 'provider'
  | 'model'
  | 'context'
  | 'maxOutput'
  | 'timeout'
  | 'thinking'
  | 'retries'
  | 'language'
export interface Problem {
  text: string
  tab: Tab
  /** Row id of the provider the problem is on. */
  provider?: string
  /** `roles.<name>`, `memory`, `learning.<scene>`, `web_search` or `web_read`. */
  place?: string
  field?: ProblemField
}

export function useModelsForm() {
  const { t } = useI18n()
  const client = useQueryClient()
  const settings = useQuery({
    queryKey: keys.host.settings(),
    queryFn: ({ signal }) => settingsApi.read(signal),
  })
  const protocols = useQuery({
    queryKey: keys.host.modelProtocols(),
    queryFn: ({ signal }) => modelsApi.protocols(signal),
    staleTime: Infinity,
  })
  const protocol = (api: string | undefined) =>
    protocols.data.value?.protocols.find((item) => item.api === api)
  const supports = (row: ProviderRow | undefined, role: string) =>
    Boolean(row && protocol(row.api)?.roles.includes(role))

  const memoryOn = computed(() => settings.data.value?.saved.memory != null)
  const saved = computed(() => (settings.data.value ? fromSnapshot(settings.data.value) : null))
  const draft = ref<ModelsDraft | null>(null)
  /** Models read from each provider, by row id; dropped when the provider's address or key changes. */
  const catalog = ref<Record<string, ListedModel[]>>({})
  const catalogLoading = ref<Record<string, boolean>>({})
  const catalogError = ref<Record<string, unknown>>({})
  const triedSave = ref(false)
  const retryErrors = reactive<Partial<Record<ChatRole, 'format' | 'max'>>>({})
  function setRetryError(role: ChatRole, error: 'format' | 'max' | null) {
    if (error) retryErrors[role] = error
    else delete retryErrors[role]
  }
  const hasRetryError = computed(() => Object.values(retryErrors).some(Boolean))
  let resetSaving = () => {}
  const adopt = () => {
    draft.value = saved.value && copy(saved.value)
    catalog.value = {}
    catalogError.value = {}
    triedSave.value = false
    for (const role of chatRoles) delete retryErrors[role]
    resetSaving()
  }
  const changeOf = (value: ModelsDraft | null) =>
    value ? JSON.stringify(toChange(value, memoryOn.value)) : ''
  const dirty = computed(
    () => Boolean(draft.value) && (changeOf(draft.value) !== changeOf(saved.value) || hasRetryError.value),
  )
  const tabDirty = computed<Record<Exclude<Tab, 'usage'>, boolean>>(() => {
    const current = draft.value
    const base = saved.value
    if (!current || !base) return { providers: false, roles: false, vectors: false }
    return {
      providers:
        JSON.stringify(toChange(current, memoryOn.value).providers) !==
        JSON.stringify(toChange(base, memoryOn.value).providers),
      roles: JSON.stringify(current.roles) !== JSON.stringify(base.roles) || hasRetryError.value,
      vectors:
        JSON.stringify([memoryOn.value ? current.memory_embedding : null, current.learning_embeddings]) !==
        JSON.stringify([memoryOn.value ? base.memory_embedding : null, base.learning_embeddings]),
    }
  })
  // Saved elsewhere meanwhile: an unchanged draft follows, an edited one is kept.
  watch(
    saved,
    (_, previous) => {
      if (!draft.value || (!hasRetryError.value && changeOf(draft.value) === changeOf(previous ?? null)))
        adopt()
    },
    { immediate: true },
  )
  watch(
    () => draft.value?.providers.map((row) => [row.id, JSON.stringify(candidateOf(row))] as const),
    (rows, before = []) => {
      const old = new Map(before)
      for (const [id, value] of rows ?? []) {
        if (old.get(id) !== value) {
          delete catalog.value[id]
          delete catalogError.value[id]
        }
      }
    },
  )

  const providerFor = (id: string | undefined) => draft.value?.providers.find((row) => row.id === id)
  const nameOf = (id: string) => providerFor(id)?.alias || t('models.providers.unnamed')
  const roleTitle = (role: string) => t(`models.roles.names.${role}`)
  async function loadCatalog(id: string): Promise<void> {
    const row = providerFor(id)
    if (!row || !hasKey(row) || !row.base_url.trim() || catalogLoading.value[id]) return
    const snapshot = JSON.stringify(candidateOf(row))
    catalogLoading.value = { ...catalogLoading.value, [id]: true }
    const cleared = { ...catalogError.value }
    delete cleared[id]
    catalogError.value = cleared
    try {
      const value = await modelsApi.list(candidateOf(row))
      const current = providerFor(id)
      if (!current || JSON.stringify(candidateOf(current)) !== snapshot) return
      catalog.value[id] = value.models
      toast.success(t('models.probe.listed', { n: value.models.length }, value.models.length))
    } catch (error) {
      const current = providerFor(id)
      if (current && JSON.stringify(candidateOf(current)) === snapshot) {
        catalogError.value = { ...catalogError.value, [id]: error }
      }
      toast.error(t('models.probe.listFailed'), {
        detail: describeError(error, t('ui.error.network')).message,
      })
    } finally {
      const next = { ...catalogLoading.value }
      delete next[id]
      catalogLoading.value = next
    }
  }
  /** Everything bound to a provider, for the list and the delete confirmation. */
  function usedBy(id: string): string[] {
    const value = draft.value
    if (!value) return []
    const resolveWeb = (connection: string | null | undefined) =>
      connection
        ? (value.providers.find((item) => item.originalAlias === connection) ??
          value.providers.find((item) => item.alias.trim() === connection))
        : undefined
    return [
      ...Object.entries(value.roles)
        .filter(([, item]) => item?.provider === id)
        .map(([role]) => roleTitle(role)),
      ...(['web_search', 'web_read'] as const)
        .filter(
          (name) =>
            resolveWeb(
              (settings.data.value?.saved[name] as { connection?: string | null } | null)?.connection,
            )?.id === id,
        )
        .map((name) => t(name === 'web_search' ? 'capabilities.web.search' : 'capabilities.web.read')),
      ...(value.memory_embedding?.provider === id ? [t('models.vectors.memory')] : []),
      ...Object.entries(value.learning_embeddings)
        .filter(([, item]) => item?.provider === id)
        .map(([scene]) => t('models.vectors.learningOf', { name: groupLabel(scene) })),
    ]
  }
  /** Providers whose protocol can serve `role`, as select options. */
  const optionsFor = (role: string) =>
    (draft.value?.providers ?? [])
      .filter((row) => supports(row, role))
      .map((row) => ({ value: row.id, label: row.alias || t('models.providers.unnamed') }))

  function addProvider(): string {
    const id = `draft:${crypto.randomUUID()}`
    const api = 'openai-chat'
    triedSave.value = false
    draft.value!.providers.push({
      id,
      alias: '',
      originalAlias: null,
      api,
      base_url: protocol(api)?.base_url ?? '',
      api_key: '',
      proxy: '',
      keyConfigured: false,
      keyFor: null,
    })
    return id
  }
  function removeProvider(id: string) {
    draft.value!.providers = draft.value!.providers.filter((row) => row.id !== id)
    delete catalog.value[id]
    delete catalogError.value[id]
  }
  function changeProtocol(row: ProviderRow, api: string) {
    const before = protocol(row.api)
    if (!row.base_url.trim() || trimUrl(row.base_url) === trimUrl(before?.base_url))
      row.base_url = protocol(api)?.base_url ?? ''
    row.api = api
    for (const role of chatRoles) {
      const binding = draft.value!.roles[role]
      if (binding?.provider === row.id) fitProtocol(binding, api)
    }
  }
  function chooseRoleProvider(role: ChatRole, id: string) {
    const binding = draft.value!.roles[role]
    if (!binding) return
    binding.provider = id
    fitProtocol(binding, providerFor(id)?.api)
  }
  function toggleRole(role: Exclude<ChatRole, 'mind'>, on: boolean) {
    if (!on) {
      draft.value!.roles[role] = null
      delete retryErrors[role]
      return
    }
    const mind = draft.value!.roles.mind
    const provider = supports(providerFor(mind.provider), role)
      ? mind.provider
      : (optionsFor(role)[0]?.value ?? '')
    const binding = newBinding(provider, role, mind)
    fitProtocol(binding, providerFor(provider)?.api)
    draft.value!.roles[role] = binding
  }
  function useStandaloneVision() {
    if (!draft.value) return
    draft.value.roles.mind.image_input = false
    if (draft.value.roles.vision === null) toggleRole('vision', true)
  }
  const syncableRoles = ['memory', 'learner', 'worker'] as const
  const canSyncFromMind = computed(() => {
    const value = draft.value
    if (!value) return false
    const mind = value.roles.mind
    const row = providerFor(mind.provider)
    return syncableRoles.some((role) => {
      const target = value.roles[role]
      return (
        target !== null &&
        supports(row, role) &&
        (target.provider !== mind.provider ||
          target.model !== mind.model ||
          target.context_window_tokens !== mind.context_window_tokens)
      )
    })
  })
  function syncCustomRolesFromMind(): number {
    const value = draft.value
    if (!value) return 0
    const mind = value.roles.mind
    const row = providerFor(mind.provider)
    let count = 0
    for (const role of syncableRoles) {
      const target = value.roles[role]
      if (!target || !supports(row, role)) continue
      target.provider = mind.provider
      target.model = mind.model
      target.context_window_tokens = mind.context_window_tokens
      fitProtocol(target, row?.api)
      count += 1
    }
    if (count > 0) toast.success(t('models.roles.syncedToCustomRoles', { n: count }, count))
    return count
  }
  function toggleAsr(on: boolean) {
    draft.value!.roles.asr = on
      ? {
          api: 'openai-audio',
          provider: optionsFor('asr')[0]?.value ?? '',
          model: '',
          timeout_seconds: 60,
          language: null,
        }
      : null
  }

  const problems = computed<Problem[]>(() => {
    const value = draft.value
    if (!value) return []
    const found: Problem[] = []
    const names = value.providers.map((row) => row.alias)
    for (const row of value.providers) {
      const on = { tab: 'providers' as const, provider: row.id }
      const name = { ...on, field: 'name' as const }
      if (!row.alias.trim()) found.push({ ...name, text: t('models.problems.noName') })
      else if (row.alias !== row.alias.trim())
        found.push({ ...name, text: t('models.problems.spaces', { name: row.alias.trim() }) })
      else if (names.filter((item) => item === row.alias).length > 1)
        found.push({ ...name, text: t('models.problems.sameName', { name: row.alias }) })
      if (!row.base_url.trim())
        found.push({ ...on, field: 'url', text: t('models.problems.noUrl', { name: nameOf(row.id) }) })
      if (!hasKey(row))
        found.push({
          ...on,
          field: 'key',
          text: row.keyConfigured
            ? t('models.problems.keyAgain', { name: nameOf(row.id) })
            : t('models.problems.noKey', { name: nameOf(row.id) }),
        })
    }
    const webRefs: [
      'web_search' | 'web_read',
      WebSearch | WebRead | null | undefined,
      Partial<Record<string, string[]>>,
    ][] = [
      ['web_search', settings.data.value?.saved.web_search as WebSearch | null | undefined, SEARCH_APIS],
      ['web_read', settings.data.value?.saved.web_read as WebRead | null | undefined, READ_APIS],
    ]
    for (const [name, config, apis] of webRefs) {
      const connection = config?.connection
      if (!connection) continue
      const service = t(name === 'web_search' ? 'capabilities.web.search' : 'capabilities.web.read')
      const row =
        value.providers.find((item) => item.originalAlias === connection) ??
        value.providers.find((item) => item.alias.trim() === connection)
      if (!row) {
        found.push({
          tab: 'providers',
          place: name,
          text: t('models.problems.webRemoved', { service, name: connection }),
        })
        continue
      }
      const allowed = apis[config.provider]
      if (allowed && !allowed.includes(row.api)) {
        found.push({
          tab: 'providers',
          provider: row.id,
          place: name,
          text: t('models.problems.unsupported', { title: service, name: nameOf(row.id) }),
        })
      }
    }
    const check = (
      title: string,
      use: string,
      item: { provider: string; model: string } | null,
      tab: Tab,
      place: string,
    ) => {
      if (!item) return
      const at = { tab, place }
      const row = providerFor(item.provider)
      if (!row) found.push({ ...at, field: 'provider', text: t('models.problems.noProvider', { title }) })
      else if (protocols.data.value && !supports(row, use))
        found.push({
          ...at,
          field: 'provider',
          text: t('models.problems.unsupported', { title, name: nameOf(row.id) }),
        })
      if (!item.model.trim())
        found.push({ ...at, field: 'model', text: t('models.problems.noModel', { title }) })
    }
    for (const role of chatRoles) {
      const binding = value.roles[role]
      const place = `roles.${role}`
      check(roleTitle(role), role, binding, 'roles', place)
      if (!binding) continue
      const at = { tab: 'roles' as const, place }
      const title = roleTitle(role)
      if (binding.context_window_tokens === null)
        found.push({ ...at, field: 'context', text: t('models.problems.noContext', { title }) })
      if (binding.max_output_tokens === null)
        found.push({ ...at, field: 'maxOutput', text: t('models.problems.noMaxOutput', { title }) })
      else if (
        binding.context_window_tokens !== null &&
        binding.max_output_tokens >= binding.context_window_tokens
      )
        found.push({ ...at, field: 'maxOutput', text: t('models.problems.outputTooLong', { title }) })
      if (binding.timeout_seconds === null)
        found.push({ ...at, field: 'timeout', text: t('models.problems.noTimeout', { title }) })
      if (binding.reasoning_effort !== null && binding.thinking_budget_tokens !== null)
        found.push({ ...at, field: 'thinking', text: t('models.problems.bothThinking', { title }) })
      const retryError = retryErrors[role]
      if (retryError)
        found.push({
          ...at,
          field: 'retries',
          text: t(retryError === 'max' ? 'models.problems.retriesMax' : 'models.problems.retriesFormat', {
            title,
          }),
        })
    }
    const asr = value.roles.asr
    check(roleTitle('asr'), 'asr', asr, 'roles', 'roles.asr')
    if (asr && asr.timeout_seconds === null)
      found.push({
        tab: 'roles',
        place: 'roles.asr',
        field: 'timeout',
        text: t('models.problems.noTimeout', { title: roleTitle('asr') }),
      })
    if (asr?.language && !/^[a-z]{2}$/.test(asr.language))
      found.push({
        tab: 'roles',
        place: 'roles.asr',
        field: 'language',
        text: t('models.problems.language'),
      })
    if (memoryOn.value)
      check(t('models.vectors.memory'), 'embedding', value.memory_embedding, 'vectors', 'memory')
    for (const [scene, item] of Object.entries(value.learning_embeddings))
      check(
        t('models.vectors.learningOf', { name: groupLabel(scene) }),
        'embedding',
        item,
        'vectors',
        `learning.${scene}`,
      )
    return found
  })

  const saving = useMutation({
    mutationFn: () => modelsApi.save(toChange(draft.value!, memoryOn.value)),
    onSuccess: (snapshot) => {
      client.setQueryData(keys.host.settings(), snapshot)
      adopt()
      void readPendingRestart()
      toast.success(t('common.saved'))
    },
  })
  resetSaving = () => {
    if (saving.isError.value) saving.reset()
  }
  watch(draft, () => resetSaving(), { deep: true })
  const saveError = computed(() =>
    saving.isError.value
      ? describeError(saving.error.value, t('ui.error.network')).message
      : (problems.value[0]?.text ?? null),
  )
  const saveRawError = computed(() =>
    saving.isError.value ? describeError(saving.error.value, t('ui.error.network')).raw : null,
  )
  const hasProblem = computed(() => !saving.isError.value && problems.value.length > 0)

  return {
    settings,
    protocols,
    protocol,
    supports,
    memoryOn,
    draft,
    catalog,
    catalogLoading,
    catalogError,
    loadCatalog,
    triedSave,
    setRetryError,
    dirty,
    tabDirty,
    adopt,
    providerFor,
    nameOf,
    roleTitle,
    usedBy,
    optionsFor,
    addProvider,
    removeProvider,
    changeProtocol,
    chooseRoleProvider,
    toggleRole,
    useStandaloneVision,
    canSyncFromMind,
    syncCustomRolesFromMind,
    toggleAsr,
    problems,
    hasProblem,
    save: () => {
      triedSave.value = true
      if (problems.value.length === 0) saving.mutate()
    },
    busy: computed(() => saving.isPending.value),
    saveError,
    saveRawError,
  }
}

export type ModelsForm = ReturnType<typeof useModelsForm>
export const modelsKey: InjectionKey<ModelsForm> = Symbol('models form')
export const useForm = () => inject(modelsKey)!
