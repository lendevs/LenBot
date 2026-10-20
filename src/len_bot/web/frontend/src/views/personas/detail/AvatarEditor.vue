<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { ImageUp, Trash2 } from '@lucide/vue'
import { avatarChanged, personaAvatar } from '../../../api/host'
import { personasApi, type PersonaRole } from '../../../api/personas'
import Avatar from '../../../ui/Avatar.vue'
import Button from '../../../ui/Button.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import { useRoleWrites } from './writes'

const props = defineProps<{ role: PersonaRole; name: string }>()

const { t } = useI18n()
const writes = useRoleWrites(computed(() => props.role.key))
const picker = ref<HTMLInputElement | null>(null)
const change = useMutation({
  mutationFn: (file: File | null) =>
    file
      ? personasApi.uploadAvatar(props.role.key, props.role.path, file)
      : personasApi.removeAvatar(props.role.key, props.role.path),
  onSuccess: (result, file) => {
    avatarChanged(props.role.key)
    writes.done(result, [], file ? t('personas.detail.avatar.changed') : t('personas.detail.avatar.removed'))
  },
  onError: (error) =>
    toast.error(t('personas.detail.avatar.failed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
})
function chosen(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) change.mutate(file)
}
async function remove() {
  const sure = await confirm({
    title: t('personas.detail.avatar.removeTitle'),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (sure) change.mutate(null)
}
</script>

<template>
  <div class="flex items-center gap-4">
    <Avatar :name="name || role.key" :src="personaAvatar(role)" :size="72" />
    <input
      ref="picker"
      type="file"
      accept="image/png,.png"
      class="sr-only"
      tabindex="-1"
      aria-hidden="true"
      @change="chosen"
    />
    <div class="flex flex-wrap items-center gap-2">
      <Button
        size="sm"
        :icon="ImageUp"
        :loading="change.isPending.value && change.variables.value !== null"
        :disabled="change.isPending.value"
        @click="picker?.click()"
      >
        {{ role.avatar ? t('personas.detail.avatar.replace') : t('personas.detail.avatar.upload') }}
      </Button>
      <Button
        v-if="role.avatar"
        size="sm"
        variant="danger-ghost"
        :icon="Trash2"
        :disabled="change.isPending.value"
        @click="remove"
      >
        {{ t('common.delete') }}
      </Button>
      <span class="w-full text-xs text-subtle">PNG</span>
    </div>
  </div>
</template>
