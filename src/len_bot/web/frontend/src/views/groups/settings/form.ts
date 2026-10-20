import { computed, inject, reactive, ref, watch, type InjectionKey, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { keys } from '../../../api/query'
import {
  settingsApi,
  type Permissions,
  type SceneChange,
  type SettingsSnapshot,
  type SpeechChange,
  type TaskChange,
} from '../../../api/settings'
import { readHostState, readPendingRestart } from '../../../api/hostStore'
import { describeError } from '../../../ui/errors'

export interface Relationship {
  account: string
  text: string
}

/** Everything the save bar saves; each part goes to its own endpoint. */
export interface Draft {
  scene: Omit<SceneChange, 'relationships'>
  relationships: Relationship[]
  tasks: TaskChange
  speech: SpeechChange
  plugins: string[]
  permissions: Permissions | null
}

const ACCOUNT = /^[a-z][a-z0-9_-]*:[^:\s/\\]+$/
const CLOCK = /^(?:[01][0-9]|2[0-3]):[0-5][0-9](?::[0-5][0-9])?$/

const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
/** Saved clocks come back as HH:MM:SS; whole minutes are edited as HH:MM. */
const minutes = (clock: string) => clock.replace(/^(\d\d:\d\d):00$/, '$1')
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

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
  const proactive = saved.proactive
  return copy({
    scene: {
      timezone: saved.timezone,
      voice_mode: saved.voice_mode,
      attention: {
        ...saved.attention,
        quiet_hours: quiet && { ...quiet, start: minutes(quiet.start), end: minutes(quiet.end) },
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
    relationships: Object.entries(saved.scene_persona.relationships).map(([account, text]) => ({
      account,
      text,
    })),
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
    return {
      ...base,
      plugins: copy(plugins.data.value?.scenes[scene.value]?.saved ?? []),
      permissions: permissions.data.value ? copy(permissions.data.value.saved) : null,
    }
  })
  const draft = ref<Draft | null>(null)
  const parts = ['scene', 'tasks', 'speech', 'plugins', 'permissions'] as const
  const changed = (part: (typeof parts)[number]) => {
    if (!draft.value || !saved.value) return false
    if (part === 'scene')
      return !same(
        [draft.value.scene, draft.value.relationships],
        [saved.value.scene, saved.value.relationships],
      )
    return !same(draft.value[part], saved.value[part])
  }
  const dirty = computed(() => parts.some(changed))

  function adopt() {
    draft.value = saved.value && copy(saved.value)
  }
  // A part read later (permissions, plugins) or saved elsewhere joins the draft when that part is unchanged.
  watch(saved, (value, previous) => {
    if (!value) return
    if (!draft.value || !previous) return adopt()
    for (const part of parts) {
      if (part === 'scene') {
        if (same([draft.value.scene, draft.value.relationships], [previous.scene, previous.relationships])) {
          draft.value.scene = copy(value.scene)
          draft.value.relationships = copy(value.relationships)
        }
      } else if (same(draft.value[part], previous[part])) {
        ;(draft.value as unknown as Record<string, unknown>)[part] = copy(value[part])
      }
    }
  })
  watch(scene, () => (draft.value = null))

  const required = t('common.required')
  /** Field errors by a dotted path such as `quiet.start`. */
  const errors = computed<Record<string, string>>(() => {
    const value = draft.value
    const found: Record<string, string> = {}
    if (!value) return found
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
      if (!(proactive.idle_seconds >= 600)) found['proactive.idle'] = t('groups.settings.errors.idle')
    }
    if (
      value.speech.mode === 'custom' &&
      !(Number.isInteger(value.speech.value) && (value.speech.value ?? 0) >= 1)
    )
      found.speech = t('groups.settings.errors.speech')
    const seen = new Set<string>()
    value.relationships.forEach((row, index) => {
      const account = row.account.trim()
      if (!ACCOUNT.test(account))
        found[`relationships.${index}.account`] = t('groups.settings.errors.account')
      else if (seen.has(account))
        found[`relationships.${index}.account`] = t('groups.settings.errors.repeated')
      seen.add(account)
      if (!row.text.trim()) found[`relationships.${index}.text`] = required
    })
    if (value.scene.persona_aliases.some((alias) => !alias.trim())) found.aliases = required
    if (attention.other_bot_ids.some((id) => !ACCOUNT.test(id)))
      found.otherBots = t('groups.settings.errors.account')
    for (const [key, number] of Object.entries(attention)) {
      if (
        typeof number !== 'number' &&
        (key.endsWith('_seconds') || key === 'activity' || key === 'max_extensions')
      )
        found[`attention.${key}`] = required
    }
    const pairs = [
      ['direct_idle_seconds', 'direct_max_seconds'],
      ['named_idle_seconds', 'named_max_seconds'],
      ['focus_idle_seconds', 'focus_max_seconds'],
      ['ambient_min_interval_seconds', 'ambient_max_interval_seconds'],
    ] as const
    for (const [low, high] of pairs) {
      if (attention[low] > attention[high]) found[`attention.${low}`] = t('groups.settings.errors.notAbove')
    }
    if (typeof value.scene.schedules.max_pending !== 'number') found.maxPending = required
    for (const key of ['max_running', 'max_daily_tasks'] as const) {
      if (typeof value.tasks[key] !== 'number') found[`tasks.${key}`] = required
    }
    return found
  })
  const invalid = computed(() => Object.keys(errors.value).length > 0)

  const saving = ref(false)
  const saveError = ref<string | null>(null)
  async function save(): Promise<boolean> {
    const value = draft.value
    if (!value || invalid.value) return false
    saving.value = true
    saveError.value = null
    const name = scene.value
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
        client.setQueryData(keys.host.settings(), await settingsApi.putScene(name, body))
      }
      if (changed('tasks'))
        client.setQueryData(keys.host.settings(), await settingsApi.putTasks(name, value.tasks))
      if (changed('speech')) {
        client.setQueryData(keys.host.settings(), await settingsApi.putSpeech(name, value.speech))
        void client.invalidateQueries({ queryKey: keys.host.limits() })
      }
      if (changed('plugins'))
        client.setQueryData(keys.plugins.all(), await settingsApi.putScenePlugins(name, value.plugins))
      if (changed('permissions') && value.permissions)
        client.setQueryData(
          keys.scene.permissions(name),
          await settingsApi.putPermissions(name, value.permissions),
        )
      adopt()
      return true
    } catch (error) {
      saveError.value = describeError(error, t('ui.error.network')).message
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
    settings,
    permissions,
    plugins,
    saved,
    draft,
    dirty,
    errors,
    invalid,
    saving,
    saveError,
    save,
    adopt,
  })
}

export type SettingsForm = ReturnType<typeof useSettingsForm>
export const formKey: InjectionKey<SettingsForm> = Symbol('settings-form')

/** The form of the settings tab, for its sections. */
export function useForm(): SettingsForm & { draft: Draft } {
  const form = inject(formKey)
  if (!form?.draft) throw new Error('settings section outside the settings tab')
  return form as SettingsForm & { draft: Draft }
}
