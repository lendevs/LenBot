import { computed, inject, ref, watch, type InjectionKey, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { keys } from '../../../api/query'
import { personasApi, type PersonaProfile } from '../../../api/personas'
import { describeError } from '../../../ui/errors'
import { useRoleWrites } from './writes'

/** The profile form is split over two tabs; each saves only its own fields onto the saved profile. */
const fields = {
  identity: ['name', 'aliases', 'self_reference', 'brief', 'behavior', 'boundaries'],
  speech: ['voice', 'styles', 'examples', 'example_tags'],
} as const satisfies Record<string, readonly (keyof PersonaProfile)[]>
export type ProfilePart = keyof typeof fields
const parts = Object.keys(fields) as ProfilePart[]

const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const pick = (profile: PersonaProfile, part: ProfilePart) =>
  Object.fromEntries(fields[part].map((field) => [field, profile[field]])) as Partial<PersonaProfile>

export function useProfileForm(key: Ref<string>) {
  const { t } = useI18n()
  const client = useQueryClient()
  const writes = useRoleWrites(key)
  const saved = useQuery({
    queryKey: computed(() => keys.personas.part(key.value, 'profile')),
    queryFn: ({ signal }) => personasApi.profile(key.value, signal),
  })
  const draft = ref<PersonaProfile | null>(null)
  /** Baseline per field that the current draft forked from, for field-level merges and conflict detection. */
  const base = ref<PersonaProfile | null>(null)

  let savingSnapshot: { targetKey: string; submitted: Partial<PersonaProfile> } | null = null

  const saving = useMutation({
    mutationFn: (part: ProfilePart) => {
      const current = saved.data.value!
      const targetKey = key.value
      const submitted = copy(pick(draft.value!, part))
      savingSnapshot = { targetKey, submitted }
      return personasApi.saveProfile(targetKey, current.directory, {
        ...current.profile,
        ...submitted,
      })
    },
    onSuccess: (result, part) => {
      const snapshot = savingSnapshot
      savingSnapshot = null
      const targetKey = snapshot?.targetKey ?? key.value
      if (key.value === targetKey && draft.value && base.value) {
        const currentDraft = draft.value as Record<string, unknown>
        const currentBase = base.value as Record<string, unknown>
        for (const field of fields[part]) {
          const nextValue = copy(result.profile[field])
          if (!snapshot || same(draft.value[field], snapshot.submitted[field])) {
            currentDraft[field] = copy(nextValue)
          }
          currentBase[field] = nextValue
        }
      }
      client.setQueryData(keys.personas.part(targetKey, 'profile'), result)
      if (key.value === targetKey) {
        writes.done(result, ['files'])
      } else {
        void client.invalidateQueries({ queryKey: keys.personas.all() })
        void client.invalidateQueries({ queryKey: keys.personas.part(targetKey, 'files') })
        void client.invalidateQueries({ queryKey: keys.personas.part(targetKey, 'preview') })
      }
    },
  })

  watch(key, () => {
    draft.value = null
    base.value = null
    saving.reset()
  })

  // Field-level merge: remote changes (from FilesTab or another session) merge into untouched fields,
  // while two-way edits to the same field keep the local draft and raise `remoteUpdated`.
  watch(
    () => saved.data.value?.profile,
    (value) => {
      if (!value) return
      if (!draft.value || !base.value) {
        draft.value = copy(value)
        base.value = copy(value)
        return
      }
      const currentDraft = draft.value
      const currentBase = base.value
      for (const part of parts) {
        for (const field of fields[part]) {
          if (same(value[field], currentBase[field])) continue
          if (same(currentDraft[field], currentBase[field]) || same(currentDraft[field], value[field])) {
            ;(currentDraft as Record<string, unknown>)[field] = copy(value[field])
            ;(currentBase as Record<string, unknown>)[field] = copy(value[field])
          }
        }
      }
    },
    { immediate: true },
  )

  const changed = (part: ProfilePart) =>
    Boolean(
      draft.value && saved.data.value && !same(pick(draft.value, part), pick(saved.data.value.profile, part)),
    )
  const dirty = computed(() => ({ identity: changed('identity'), speech: changed('speech') }))

  const hasConflict = (part: ProfilePart) => {
    const currentDraft = draft.value
    const currentBase = base.value
    const currentSaved = saved.data.value?.profile
    if (!currentDraft || !currentBase || !currentSaved) return false
    return fields[part].some(
      (field) =>
        !same(currentDraft[field], currentBase[field]) &&
        !same(currentSaved[field], currentBase[field]) &&
        !same(currentDraft[field], currentSaved[field]),
    )
  }
  const remoteUpdated = computed(() => ({
    identity: hasConflict('identity'),
    speech: hasConflict('speech'),
  }))

  /** First problem that blocks saving a part, as the save bar shows it. */
  function problem(part: ProfilePart): string | null {
    const value = draft.value
    if (!value) return null
    if (part === 'identity') return value.name.trim() ? null : t('personas.detail.problems.name')
    if (value.styles.some((style) => !style.name.trim())) return t('personas.detail.problems.styleName')
    if (value.styles.length) {
      const total = value.styles.reduce((sum, style) => sum + style.weight, 0)
      if (Math.abs(total - 1) > 1e-6) {
        return t('personas.detail.problems.styleTotal', { n: Math.round(total * 10000) / 100 })
      }
    }
    if (value.examples.some((example) => !example.context.trim() || !example.line.trim())) {
      return t('personas.detail.problems.example')
    }
    return null
  }

  const save = (part: ProfilePart) => {
    if (changed(part) && !problem(part) && !saving.isPending.value) saving.mutate(part)
  }
  const isSaving = (part: ProfilePart) => saving.isPending.value && saving.variables.value === part
  const saveError = (part: ProfilePart) =>
    saving.isError.value && saving.variables.value === part
      ? describeError(saving.error.value, t('ui.error.network')).message
      : null
  const saveRawError = (part: ProfilePart) =>
    saving.isError.value && saving.variables.value === part
      ? describeError(saving.error.value, t('ui.error.network')).raw
      : null

  function discard(part: ProfilePart) {
    if (draft.value && base.value && saved.data.value) {
      const savedPart = copy(pick(saved.data.value.profile, part))
      Object.assign(draft.value, savedPart)
      Object.assign(base.value, copy(savedPart))
    }
    if (saving.variables.value === part) saving.reset()
  }

  /** Role files of the whole draft, saved or not, for a draft trial. */
  async function draftFiles() {
    const { directory, files } = await personasApi.draft(key.value, saved.data.value!.directory, draft.value!)
    return { directory, files }
  }

  return {
    saved,
    draft,
    dirty,
    remoteUpdated,
    problem,
    save,
    isSaving,
    saveError,
    saveRawError,
    discard,
    draftFiles,
  }
}

export type ProfileForm = ReturnType<typeof useProfileForm>
export const profileKey: InjectionKey<ProfileForm> = Symbol('profile-form')

export function useProfile(): ProfileForm {
  const form = inject(profileKey)
  if (!form) throw new Error('useProfile() needs the persona detail page')
  return form
}
