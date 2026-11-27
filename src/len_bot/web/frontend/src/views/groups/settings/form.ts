import { computed, inject, reactive, ref, watch, type InjectionKey, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { keys } from '../../../api/query'
import {
  settingsApi,
  type Permissions,
  type SceneChange,
  type SemanticPulse,
  type SettingsSnapshot,
  type SpeechChange,
  type TaskChange,
} from '../../../api/settings'
import { readHostState, readPendingRestart } from '../../../api/hostStore'
import type { SceneMemory } from '../../../api/plugins'
import { describeError } from '../../../ui/errors'

export interface Relationship {
  id: number
  account: string
  text: string
}

let nextRelationshipId = 1
export function createRelationship(account = '', text = ''): Relationship {
  return { id: nextRelationshipId++, account, text }
}

export type SettingsSectionId =
  | 'role'
  | 'participation'
  | 'focus'
  | 'quiet'
  | 'speech'
  | 'proactive'
  | 'persona'
  | 'tasks'
  | 'plugins'
  | 'permissions'
  | 'danger'

/** Everything the save bar saves; each part goes to its own endpoint. */
export interface Draft {
  scene: Omit<SceneChange, 'relationships'>
  relationships: Relationship[]
  tasks: TaskChange
  speech: SpeechChange
  plugins: string[]
  memory: SceneMemory
  permissions: Permissions | null
}

const ACCOUNT = /^[a-z][a-z0-9_-]*:[^:\s/\\]+$/
const CLOCK = /^(?:[01][0-9]|2[0-3]):[0-5][0-9](?::[0-5][0-9])?$/

export const cloneValue = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
/** Saved clocks come back as HH:MM:SS; whole minutes are edited as HH:MM. */
const minutes = (clock: string) => clock.replace(/^(\d\d:\d\d):00$/, '$1')
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const isFiniteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value)
const DEFAULT_PULSE: SemanticPulse = { mode: 'off', sample_interval_seconds: 120 }

const participationSlice = (draft: Draft) => {
  const { attention, timezone, transcribe_audio } = draft.scene
  return {
    only_direct: attention.only_direct,
    keywords: attention.keywords,
    pulse: attention.pulse,
    other_bot_ids: attention.other_bot_ids,
    timezone,
    transcribe_audio,
    direct_idle_seconds: attention.direct_idle_seconds,
    direct_max_seconds: attention.direct_max_seconds,
    named_idle_seconds: attention.named_idle_seconds,
    named_max_seconds: attention.named_max_seconds,
    keyword_cooldown_seconds: attention.keyword_cooldown_seconds,
    focus_seconds: attention.focus_seconds,
    focus_idle_seconds: attention.focus_idle_seconds,
    focus_max_seconds: attention.focus_max_seconds,
    ambient_min_interval_seconds: attention.ambient_min_interval_seconds,
    ambient_max_interval_seconds: attention.ambient_max_interval_seconds,
    speech_burst: attention.speech_burst,
    speech_interval_seconds: attention.speech_interval_seconds,
    explore_probability: attention.explore_probability,
    max_extensions: attention.max_extensions,
  }
}

const relationshipsComparable = (rows: Relationship[]) => rows.map(({ account, text }) => [account, text])

const sceneComparable = (draft: Draft) => [draft.scene, relationshipsComparable(draft.relationships)]

function sceneOf(
  snapshot: SettingsSnapshot,
  scene: string,
): Pick<Draft, 'scene' | 'relationships' | 'tasks' | 'speech'> | null {
  const saved = snapshot.saved.scenes[scene]
  if (!saved) return null
  const table = snapshot.saved.limits.scene_messages_per_hour ?? {}
  const {
    enabled,
    max_running,
    max_daily_tasks,
    egress_max_task_bytes,
    egress_max_daily_bytes,
    egress_bytes_per_second,
  } = saved.tasks
  const quiet = saved.attention.quiet_hours
  const pulse = saved.attention.pulse
  const proactive = saved.proactive
  return cloneValue({
    scene: {
      timezone: saved.timezone,
      voice_mode: saved.voice_mode,
      attention: {
        ...saved.attention,
        quiet_hours: quiet && { ...quiet, start: minutes(quiet.start), end: minutes(quiet.end) },
        pulse: pulse
          ? {
              mode: pulse.mode ?? DEFAULT_PULSE.mode,
              sample_interval_seconds: pulse.sample_interval_seconds ?? DEFAULT_PULSE.sample_interval_seconds,
            }
          : { ...DEFAULT_PULSE },
      },
      schedules: {
        enabled: saved.schedules.enabled,
        max_pending: saved.schedules.max_pending,
        autonomous: saved.schedules.autonomous,
      },
      proactive: proactive && { ...proactive, start: minutes(proactive.start), end: minutes(proactive.end) },
      transcribe_audio: saved.transcribe_audio,
      persona_aliases: saved.scene_persona.persona_aliases,
      behavior_addendum: saved.scene_persona.behavior_addendum,
    },
    relationships: Object.entries(saved.scene_persona.relationships).map(([account, text]) =>
      createRelationship(account, text),
    ),
    tasks: {
      enabled,
      max_running,
      max_daily_tasks,
      egress_max_task_bytes,
      egress_max_daily_bytes,
      egress_bytes_per_second,
    },
    speech: !(scene in table)
      ? { mode: 'global', value: null }
      : table[scene] === null
        ? { mode: 'unlimited', value: null }
        : { mode: 'custom', value: table[scene] },
  })
}

export function errorSection(key: string): SettingsSectionId {
  if (key.startsWith('attention.declarations.') || key.startsWith('attention.disposition.')) return 'focus'
  if (key.startsWith('attention.') || key === 'otherBots') return 'participation'
  if (key.startsWith('quiet.')) return 'quiet'
  if (key === 'speech') return 'speech'
  if (key.startsWith('proactive.')) return 'proactive'
  if (key === 'aliases' || key.startsWith('relationships.')) return 'persona'
  if (key === 'maxPending' || key.startsWith('tasks.')) return 'tasks'
  if (key.startsWith('permissions.')) return 'permissions'
  return 'participation'
}

export function useSettingsForm(scene: Ref<string>) {
  const { t } = useI18n()
  const client = useQueryClient()
  const settings = useQuery({
    queryKey: keys.host.settings(),
    queryFn: ({ signal }) => settingsApi.read(signal),
  })
  const permissions = useQuery({
    queryKey: computed(() => keys.scene.permissions(scene.value)),
    queryFn: ({ signal }) => settingsApi.permissions(scene.value, signal),
  })
  const plugins = useQuery({
    queryKey: keys.plugins.all(),
    queryFn: ({ signal }) => settingsApi.plugins(signal),
  })

  /** What is saved now, in the draft's shape; null until the settings are read. */
  const saved = computed<Draft | null>(() => {
    const snapshot = settings.data.value
    const base = snapshot && sceneOf(snapshot, scene.value)
    if (!base) return null
    const entry = plugins.data.value?.scenes[scene.value]
    return {
      ...base,
      plugins: cloneValue(entry?.saved ?? []),
      memory: {
        memory_plugin: entry?.memory_plugin.saved ?? null,
        recap_plugin: entry?.recap_plugin.saved ?? null,
      },
      permissions: permissions.data.value ? cloneValue(permissions.data.value.saved) : null,
    }
  })
  const draft = ref<Draft | null>(null)
  const parts = ['scene', 'tasks', 'speech', 'plugins', 'memory', 'permissions'] as const
  const changed = (part: (typeof parts)[number]) => {
    if (!draft.value || !saved.value) return false
    if (part === 'scene') return !same(sceneComparable(draft.value), sceneComparable(saved.value))
    return !same(draft.value[part], saved.value[part])
  }
  const dirty = computed(() => parts.some(changed))
  /** The memory implementation itself; a recap change alone needs no confirmation. */
  const memoryChanged = computed(
    () =>
      !!draft.value && !!saved.value && draft.value.memory.memory_plugin !== saved.value.memory.memory_plugin,
  )

  const expanded = reactive({
    participationDetails: false,
    focusDetails: false,
    tasksTraffic: false,
    permissionsScoped: false,
  })

  const saving = ref(false)
  const saveError = ref<string | null>(null)
  const saveRawError = ref<string | null>(null)
  function clearSaveError() {
    saveError.value = null
    saveRawError.value = null
  }

  function adopt() {
    draft.value = saved.value && cloneValue(saved.value)
    clearSaveError()
  }
  // A part read later (permissions, plugins) or saved elsewhere joins the draft when that part is unchanged.
  // Immediate: returning to the tab finds the settings already cached, so `saved` does not change again.
  watch(
    saved,
    (value, previous) => {
      if (!value) return
      if (!draft.value || !previous) return adopt()
      for (const part of parts) {
        if (part === 'scene') {
          if (same(sceneComparable(draft.value), sceneComparable(previous))) {
            draft.value.scene = cloneValue(value.scene)
            draft.value.relationships = cloneValue(value.relationships)
          }
        } else if (same(draft.value[part], previous[part])) {
          ;(draft.value as unknown as Record<string, unknown>)[part] = cloneValue(value[part])
        }
      }
    },
    { immediate: true },
  )
  // Another group starts from its own saved settings, whichever of the two watchers runs first.
  watch(scene, adopt)
  watch(
    draft,
    () => {
      if (saveError.value || saveRawError.value) clearSaveError()
    },
    { deep: true },
  )

  /** Field errors by a dotted path such as `quiet.start`. */
  const errors = computed<Record<string, string>>(() => {
    const value = draft.value
    const found: Record<string, string> = {}
    if (!value) return found
    const required = t('common.required')
    const positive = t('groups.settings.errors.positive')
    const atLeastOne = t('groups.settings.errors.atLeastOne')
    const nonNegativeInt = t('groups.settings.errors.nonNegativeInt')
    const accountErr = t('groups.settings.errors.account')
    const attention = value.scene.attention
    const clock = (key: string, text: string | undefined) => {
      if (!text) found[key] = required
      else if (!CLOCK.test(text)) found[key] = t('groups.settings.errors.clock')
    }
    const quiet = attention.quiet_hours
    if (quiet) {
      clock('quiet.start', quiet.start)
      clock('quiet.end', quiet.end)
      if (!found['quiet.end'] && quiet.start === quiet.end)
        found['quiet.end'] = t('groups.settings.errors.samePeriod')
      if (quiet.direct === 'notice' && !quiet.notice_text?.trim()) found['quiet.notice'] = required
    }
    const proactive = value.scene.proactive
    if (proactive) {
      clock('proactive.start', proactive.start)
      clock('proactive.end', proactive.end)
      if (!found['proactive.end'] && proactive.start === proactive.end)
        found['proactive.end'] = t('groups.settings.errors.samePeriod')
      if (!isFiniteNumber(proactive.idle_seconds) || !(proactive.idle_seconds >= 600))
        found['proactive.idle'] = t('groups.settings.errors.idle')
    }
    if (
      value.speech.mode === 'custom' &&
      !(Number.isInteger(value.speech.value) && (value.speech.value ?? 0) >= 1)
    )
      found.speech = t('groups.settings.errors.speech')
    const seen = new Set<string>()
    value.relationships.forEach((row, index) => {
      const account = row.account.trim()
      if (!ACCOUNT.test(account)) found[`relationships.${index}.account`] = accountErr
      else if (seen.has(account))
        found[`relationships.${index}.account`] = t('groups.settings.errors.repeated')
      seen.add(account)
      if (!row.text.trim()) found[`relationships.${index}.text`] = required
    })
    if (value.scene.persona_aliases.some((alias) => !alias.trim())) found.aliases = required
    if (attention.other_bot_ids.some((id) => !ACCOUNT.test(id))) found.otherBots = accountErr

    const positiveSeconds = new Set([
      'direct_max_seconds',
      'named_max_seconds',
      'focus_max_seconds',
      'ambient_min_interval_seconds',
      'ambient_max_interval_seconds',
    ])
    for (const [key, number] of Object.entries(attention)) {
      if (key.endsWith('_seconds')) {
        if (!isFiniteNumber(number)) found[`attention.${key}`] = required
        else if (positiveSeconds.has(key) && number <= 0) found[`attention.${key}`] = positive
        else if (number < 0) found[`attention.${key}`] = nonNegativeInt
      }
    }
    if (!isFiniteNumber(attention.speech_burst)) found['attention.speech_burst'] = required
    else if (!Number.isInteger(attention.speech_burst) || attention.speech_burst < 1)
      found['attention.speech_burst'] = atLeastOne

    if (!isFiniteNumber(attention.max_extensions)) found['attention.max_extensions'] = required
    else if (!Number.isInteger(attention.max_extensions) || attention.max_extensions < 0)
      found['attention.max_extensions'] = nonNegativeInt

    if (!isFiniteNumber(attention.explore_probability)) found['attention.explore_probability'] = required
    else if (attention.explore_probability < 0 || attention.explore_probability > 1)
      found['attention.explore_probability'] = t('groups.settings.errors.probability')

    if (!isFiniteNumber(attention.pulse?.sample_interval_seconds))
      found['attention.pulse.sample_interval_seconds'] = required
    else if (attention.pulse.sample_interval_seconds < 0)
      found['attention.pulse.sample_interval_seconds'] = nonNegativeInt

    const pairs = [
      ['direct_idle_seconds', 'direct_max_seconds'],
      ['named_idle_seconds', 'named_max_seconds'],
      ['focus_idle_seconds', 'focus_max_seconds'],
      ['ambient_min_interval_seconds', 'ambient_max_interval_seconds'],
    ] as const
    for (const [low, high] of pairs) {
      if (
        isFiniteNumber(attention[low]) &&
        isFiniteNumber(attention[high]) &&
        attention[low] > attention[high]
      )
        found[`attention.${low}`] = t('groups.settings.errors.notAbove')
    }

    if (attention.declarations) {
      const dec = attention.declarations
      if (!isFiniteNumber(dec.max_minutes)) found['attention.declarations.max_minutes'] = required
      else if (dec.max_minutes <= 0) found['attention.declarations.max_minutes'] = positive
      for (const key of ['max_intents', 'max_conditions', 'max_people', 'max_keywords'] as const) {
        if (!isFiniteNumber(dec[key])) found[`attention.declarations.${key}`] = required
        else if (!Number.isInteger(dec[key]) || dec[key] < 1)
          found[`attention.declarations.${key}`] = atLeastOne
      }
    }

    if (attention.disposition) {
      const disp = attention.disposition
      if (!isFiniteNumber(disp.max_minutes)) found['attention.disposition.max_minutes'] = required
      else if (disp.max_minutes <= 0) found['attention.disposition.max_minutes'] = positive
      if (!isFiniteNumber(disp.max_people)) found['attention.disposition.max_people'] = required
      else if (!Number.isInteger(disp.max_people) || disp.max_people < 1)
        found['attention.disposition.max_people'] = atLeastOne
    }

    if (!isFiniteNumber(value.scene.schedules.max_pending)) found.maxPending = required
    else if (!Number.isInteger(value.scene.schedules.max_pending) || value.scene.schedules.max_pending < 1)
      found.maxPending = atLeastOne

    for (const key of ['max_running', 'max_daily_tasks'] as const) {
      const current = value.tasks[key]
      if (!isFiniteNumber(current)) found[`tasks.${key}`] = required
      else if (!Number.isInteger(current) || current < 1) found[`tasks.${key}`] = atLeastOne
    }

    if (value.permissions) {
      const perms = value.permissions
      if (perms.scene_identities) {
        for (const list of ['admins', 'whitelist', 'blacklist'] as const) {
          if (perms.scene_identities[list].some((id) => !ACCOUNT.test(id)))
            found[`permissions.scene.${list}`] = accountErr
        }
      }
      for (const scope of ['task_identities', 'schedule_identities'] as const) {
        const scoped = perms[scope]
        if (scoped.owner && !ACCOUNT.test(scoped.owner)) found[`permissions.${scope}.owner`] = accountErr
        for (const list of ['admins', 'whitelist'] as const) {
          if (scoped[list].some((id) => !ACCOUNT.test(id))) found[`permissions.${scope}.${list}`] = accountErr
        }
      }
    }

    return found
  })
  const invalid = computed(() => Object.keys(errors.value).length > 0)

  const sectionDirty = computed<Record<SettingsSectionId, boolean>>(() => {
    const d = draft.value
    const s = saved.value
    if (!d || !s) {
      return {
        role: false,
        participation: false,
        focus: false,
        quiet: false,
        speech: false,
        proactive: false,
        persona: false,
        tasks: false,
        plugins: false,
        permissions: false,
        danger: false,
      }
    }
    return {
      role: false,
      participation: !same(participationSlice(d), participationSlice(s)),
      focus: !same(
        [d.scene.attention.declarations, d.scene.attention.disposition],
        [s.scene.attention.declarations, s.scene.attention.disposition],
      ),
      quiet: !same(d.scene.attention.quiet_hours, s.scene.attention.quiet_hours),
      speech: changed('speech'),
      proactive: !same(d.scene.proactive, s.scene.proactive),
      persona: !same(
        [d.scene.persona_aliases, d.scene.behavior_addendum, relationshipsComparable(d.relationships)],
        [s.scene.persona_aliases, s.scene.behavior_addendum, relationshipsComparable(s.relationships)],
      ),
      tasks: !same(d.scene.schedules, s.scene.schedules) || changed('tasks'),
      plugins: changed('plugins') || changed('memory'),
      permissions: changed('permissions'),
      danger: false,
    }
  })

  const sectionErrors = computed<Record<SettingsSectionId, boolean>>(() => {
    const map: Record<SettingsSectionId, boolean> = {
      role: false,
      participation: false,
      focus: false,
      quiet: false,
      speech: false,
      proactive: false,
      persona: false,
      tasks: false,
      plugins: false,
      permissions: false,
      danger: false,
    }
    for (const key of Object.keys(errors.value)) {
      map[errorSection(key)] = true
    }
    return map
  })

  async function save(): Promise<'saved' | 'restart' | false> {
    const value = draft.value
    if (!value || invalid.value) return false
    saving.value = true
    clearSaveError()
    const name = scene.value
    let restartRequired = false
    try {
      if (changed('scene')) {
        const body: SceneChange = {
          ...value.scene,
          timezone: value.scene.timezone?.trim() || null,
          behavior_addendum: value.scene.behavior_addendum?.trim() || null,
          relationships: Object.fromEntries(
            value.relationships.map((row) => [row.account.trim(), row.text.trim()]),
          ),
        }
        const snapshot = await settingsApi.putScene(name, body)
        client.setQueryData(keys.host.settings(), snapshot)
        if (snapshot.restart_required.scenes?.[name]) restartRequired = true
      }
      if (changed('tasks')) {
        const snapshot = await settingsApi.putTasks(name, value.tasks)
        client.setQueryData(keys.host.settings(), snapshot)
        if (snapshot.restart_required.scenes?.[name]) restartRequired = true
      }
      if (changed('speech')) {
        const snapshot = await settingsApi.putSpeech(name, value.speech)
        client.setQueryData(keys.host.settings(), snapshot)
        if (snapshot.restart_required.scenes?.[name]) restartRequired = true
        void client.invalidateQueries({ queryKey: keys.host.limits() })
      }
      if (changed('plugins') || changed('memory')) {
        const snapshot = await settingsApi.putScenePlugins(name, value.plugins, value.memory)
        client.setQueryData(keys.plugins.all(), snapshot)
        if (snapshot.restart_required) restartRequired = true
      }
      if (changed('permissions') && value.permissions) {
        const snapshot = await settingsApi.putPermissions(name, value.permissions)
        client.setQueryData(keys.scene.permissions(name), snapshot)
        if (snapshot.restart_required) restartRequired = true
      }
      adopt()
      return restartRequired ? 'restart' : 'saved'
    } catch (error) {
      const described = describeError(error, t('ui.error.network'))
      saveError.value = described.message
      saveRawError.value = described.raw
      // Parts saved before the failure are kept; read again so the draft compares with what is saved now.
      void client.invalidateQueries({ queryKey: keys.host.settings() })
      return false
    } finally {
      saving.value = false
      void readPendingRestart()
      void readHostState()
    }
  }

  return reactive({
    scene,
    settings,
    permissions,
    plugins,
    saved,
    draft,
    dirty,
    memoryChanged,
    errors,
    invalid,
    sectionDirty,
    sectionErrors,
    expanded,
    saving,
    saveError,
    saveRawError,
    save,
    adopt,
  })
}

/** An account typed as the bare number gets the platform of the scene it is configured in. */
export function withPlatform(scene: string, account: string): string {
  const value = account.trim()
  return !value || value.includes(':') ? value : `${scene.split(':', 1)[0]}:${value}`
}

export type SettingsForm = ReturnType<typeof useSettingsForm>
export const formKey: InjectionKey<SettingsForm> = Symbol('settings-form')

/** The form of the settings tab, for its sections. */
export function useForm(): SettingsForm & { draft: Draft } {
  const form = inject(formKey)
  if (!form?.draft) throw new Error('settings section outside the settings tab')
  return form as SettingsForm & { draft: Draft }
}
