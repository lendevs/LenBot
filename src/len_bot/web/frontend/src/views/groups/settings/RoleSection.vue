<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ArrowUpRight } from '@lucide/vue'
import { hostApi, personaAvatar, type PersonaSummary } from '../../../api/host'
import { keys } from '../../../api/query'
import { settingsApi } from '../../../api/settings'
import { readHostState } from '../../../host/store.js'
import { groupLabel } from '../../../layouts/shell/scenes'
import Avatar from '../../../ui/Avatar.vue'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import Select from '../../../ui/Select.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import { useForm } from './form'

const props = defineProps<{ scene: string }>()

const { t } = useI18n()
const client = useQueryClient()
const form = useForm()
const personas = useQuery({ queryKey: keys.personas.all(), queryFn: ({ signal }) => hostApi.personas(signal) })
const roles = computed(() => personas.data.value?.roles ?? [])
const label = (role: PersonaSummary) => role.name || role.key
const current = computed(() => roles.value.find((role) => role.path === form.settings.data?.saved.scenes[props.scene]?.persona))
const options = computed(() =>
  roles.value
    .filter((role) => !role.error && (!role.duplicate_id || role === current.value))
    .map((role) => ({ value: role.key, label: label(role) })),
)

const use = useMutation({
  mutationFn: (role: PersonaSummary) => settingsApi.useRole(role.key, [props.scene]),
  onSuccess: ({ results }, role) => {
    const result = results[0]
    if (result?.status === 'failed') {
      toast.error(t('groups.settings.role.failed'), { detail: result.error })
      return
    }
    if (result?.status === 'pending') toast.success(t('groups.settings.role.pending', { name: label(role) }))
    else toast.success(t('groups.settings.role.done', { name: label(role) }))
    if (result?.handover === 'failed') toast.error(t('groups.settings.role.handoverFailed'))
  },
  onError: (error) =>
    toast.error(t('groups.settings.role.failed'), { detail: describeError(error, t('ui.error.network')).message }),
  onSettled: () => {
    void client.invalidateQueries({ queryKey: keys.personas.all() })
    void client.invalidateQueries({ queryKey: keys.host.settings() })
    void readHostState()
  },
})

const selected = computed({
  get: () => current.value?.key,
  set: (key: string | undefined) => void choose(key),
})
// Aliases, relationships and the extra requirement belong to the role, so the form is read again afterwards.
async function choose(key: string | undefined) {
  const role = roles.value.find((item) => item.key === key)
  if (!role || role === current.value) return
  if (form.dirty) {
    const discard = await confirm({ title: t('groups.settings.role.discard'), confirmLabel: t('common.discard') })
    if (!discard) return
    form.adopt()
  }
  const confirmed = await confirm({
    title: t('groups.settings.role.title', { group: groupLabel(props.scene), name: label(role) }),
    confirmLabel: t('groups.settings.role.action'),
    tone: 'primary',
  })
  if (confirmed) use.mutate(role)
}
</script>

<template>
  <FormSection :title="t('groups.settings.role.section')" :columns="1">
    <ErrorNote
      v-if="personas.isError.value"
      :title="t('groups.settings.role.readFailed')"
      :error="personas.error.value"
      :retry="personas.refetch"
    />
    <div class="flex flex-wrap items-end gap-3">
      <span v-if="current" class="flex pb-0.5" aria-hidden="true">
        <Avatar :name="label(current)" :src="personaAvatar(current)" :size="36" />
      </span>
      <Field :label="t('groups.settings.role.label')" class="min-w-0 flex-1 sm:max-w-80">
        <Select
          v-model="selected"
          :options="options"
          :disabled="use.isPending.value || personas.isPending.value"
          :placeholder="personas.isPending.value ? t('common.loading') : undefined"
        />
      </Field>
      <Button
        v-if="current"
        variant="ghost"
        :icon-right="ArrowUpRight"
        :to="{ name: 'host-persona', query: { persona: current.key } }"
      >
        {{ t('groups.settings.role.edit') }}
      </Button>
    </div>
  </FormSection>
</template>
