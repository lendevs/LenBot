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

  // A part saved elsewhere (raw files, the other tab) joins the draft when the draft left that part unchanged.
  watch(
    () => saved.data.value?.profile,
    (value, previous) => {
      if (!value) return
      if (!draft.value || !previous) {
        draft.value = copy(value)
        return
      }
      for (const part of parts) {
        if (same(pick(draft.value, part), pick(previous, part)))
          Object.assign(draft.value, copy(pick(value, part)))
      }
    },
    { immediate: true },
  )

  const changed = (part: ProfilePart) =>
    Boolean(
      draft.value && saved.data.value && !same(pick(draft.value, part), pick(saved.data.value.profile, part)),
    )
  const dirty = computed(() => ({ identity: changed('identity'), speech: changed('speech') }))

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

  const saving = useMutation({
    mutationFn: (part: ProfilePart) => {
      const current = saved.data.value!
      return personasApi.saveProfile(key.value, current.directory, {
        ...current.profile,
        ...pick(draft.value!, part),
      })
    },
    onSuccess: (result) => {
      client.setQueryData(keys.personas.part(key.value, 'profile'), result)
      writes.done(result, ['files'])
    },
  })
  const save = (part: ProfilePart) => {
    if (changed(part) && !problem(part) && !saving.isPending.value) saving.mutate(part)
  }
  const isSaving = (part: ProfilePart) => saving.isPending.value && saving.variables.value === part
  const saveError = (part: ProfilePart) =>
    saving.isError.value && saving.variables.value === part
      ? describeError(saving.error.value, t('ui.error.network')).message
      : null

  function discard(part: ProfilePart) {
    if (draft.value && saved.data.value)
      Object.assign(draft.value, copy(pick(saved.data.value.profile, part)))
  }

  /** Role files of the whole draft, saved or not, for a draft trial. */
  async function draftFiles() {
    const { directory, files } = await personasApi.draft(key.value, saved.data.value!.directory, draft.value!)
    return { directory, files }
  }

  return { saved, draft, dirty, problem, save, isSaving, saveError, discard, draftFiles }
}

export type ProfileForm = ReturnType<typeof useProfileForm>
export const profileKey: InjectionKey<ProfileForm> = Symbol('profile-form')

export function useProfile(): ProfileForm {
  const form = inject(profileKey)
  if (!form) throw new Error('useProfile() needs the persona detail page')
  return form
}
