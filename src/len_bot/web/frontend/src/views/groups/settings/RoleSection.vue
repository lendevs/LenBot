<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpRight } from '@lucide/vue'
import { personaAvatar, type HostScene } from '../../../api/host'
import { host } from '../../../api/hostStore'
import { groupLabel } from '../../../layouts/shell/scenes'
import Avatar from '../../../ui/Avatar.vue'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import Select from '../../../ui/Select.vue'
import { confirm } from '../../../ui/confirm'
import { roleLabel, useRoleSwitch, useRoles } from '../roleSwitch'
import { useForm } from './form'

const props = defineProps<{ scene: string }>()

const { t } = useI18n()
const form = useForm()
const { library, roles, usable } = useRoles()
const { switchRole, sending } = useRoleSwitch()
const current = computed(() => roles.value.find((role) => role.path === form.settings.data?.saved.scenes[props.scene]?.persona))
const waiting = computed(
  () => ((host.state?.scenes ?? []) as HostScene[]).find((item) => item.scene === props.scene)?.persona_switch ?? null,
)
const options = computed(() =>
  [...usable.value, ...(current.value && !usable.value.includes(current.value) ? [current.value] : [])].map((role) => ({
    value: role.key,
    label: roleLabel(role),
  })),
)

const selected = computed({
  get: () => waiting.value?.key ?? current.value?.key,
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
    title: t('groups.settings.role.title', { group: groupLabel(props.scene), name: roleLabel(role) }),
    confirmLabel: t('groups.settings.role.action'),
    tone: 'primary',
  })
  if (confirmed) switchRole(props.scene, role)
}
</script>

<template>
  <FormSection :title="t('groups.settings.role.section')" :columns="1">
    <ErrorNote
      v-if="library.isError.value"
      :title="t('groups.settings.role.readFailed')"
      :error="library.error.value"
      :retry="library.refetch"
    />
    <div class="flex flex-wrap items-end gap-3">
      <span v-if="current" class="flex pb-0.5" aria-hidden="true">
        <Avatar :name="roleLabel(current)" :src="personaAvatar(current)" :size="36" />
      </span>
      <Field :label="t('groups.settings.role.label')" class="min-w-0 flex-1 sm:max-w-80">
        <Select
          v-model="selected"
          :options="options"
          :disabled="sending(scene) || Boolean(waiting) || library.isPending.value"
          :placeholder="library.isPending.value ? t('common.loading') : undefined"
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
    <div v-if="waiting">
      <Badge tone="warning" dot pulse>{{ t('groups.settings.role.waiting', { name: waiting.name }) }}</Badge>
    </div>
  </FormSection>
</template>
