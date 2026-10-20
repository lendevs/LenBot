import { computed, ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { keys } from '../../api/query'
import { settingsApi, type SettingsSnapshot } from '../../api/settings'
import { useUnsavedChanges } from '../../composables/useUnsavedChanges.js'
import { readPendingRestart } from '../../host/store.js'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

export const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
export const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

/**
 * One section of GET /api/host/settings edited on its own: a draft copied from the saved value, kept while the
 * user edits and replaced when the saved value changes underneath an untouched draft.
 */
export function useSettingsDraft<T>(options: {
  pick: (snapshot: SettingsSnapshot) => T
  save: (draft: T) => Promise<SettingsSnapshot>
  /** Key of `restart_required` that says whether the saved value waits for a restart. */
  section: string
  /** Typed values outside the draft, such as a new password, that also count as unsaved. */
  extra?: () => boolean
  /** Clears the values behind `extra`; called after saving and on discard. */
  reset?: () => void
  /** Before saving; false cancels. */
  confirm?: (draft: T) => Promise<boolean>
  onSaved?: (snapshot: SettingsSnapshot) => void
}) {
  const { t } = useI18n()
  const client = useQueryClient()
  const settings = useQuery({ queryKey: keys.host.settings(), queryFn: ({ signal }) => settingsApi.read(signal) })
  const saved = computed(() => (settings.data.value ? options.pick(settings.data.value) : undefined))
  const draft = ref(saved.value === undefined ? undefined : copy(saved.value)) as Ref<T | undefined>
  watch(saved, (next, previous) => {
    if (next !== undefined && (previous === undefined || draft.value === undefined || same(draft.value, previous)))
      draft.value = copy(next)
  })
  const dirty = computed(
    () => draft.value !== undefined && (!same(draft.value, saved.value) || Boolean(options.extra?.())),
  )
  useUnsavedChanges(dirty, { keep: ['tab'] })

  const save = useMutation({
    mutationFn: () => options.save(draft.value as T),
    onSuccess: (snapshot) => {
      client.setQueryData(keys.host.settings(), snapshot)
      draft.value = copy(options.pick(snapshot))
      options.reset?.()
      options.onSaved?.(snapshot)
      void readPendingRestart()
      const pending = (snapshot.restart_required as Record<string, unknown>)[options.section]
      toast.success(pending ? t('system.savedRestart') : t('common.saved'))
    },
  })
  async function submit() {
    if (draft.value === undefined) return
    if (options.confirm && !(await options.confirm(draft.value))) return
    save.mutate()
  }
  const saveError = computed(() =>
    save.isError.value ? describeError(save.error.value, t('ui.error.network')).message : null,
  )
  const discard = () => {
    if (saved.value !== undefined) draft.value = copy(saved.value)
    options.reset?.()
    save.reset()
  }
  const saving = computed(() => save.isPending.value)
  return { settings, saved, draft, dirty, saving, submit, saveError, discard }
}
