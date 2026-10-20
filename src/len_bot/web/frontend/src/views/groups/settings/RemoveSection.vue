<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { Trash2 } from '@lucide/vue'
import { keys } from '../../../api/query'
import { settingsApi } from '../../../api/settings'
import { readHostState } from '../../../host/store.js'
import { groupLabel } from '../../../layouts/shell/scenes'
import Button from '../../../ui/Button.vue'
import FormSection from '../../../ui/FormSection.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'

const props = defineProps<{ scene: string }>()

const { t } = useI18n()
const router = useRouter()
const client = useQueryClient()
const remove = useMutation({
  mutationFn: () => settingsApi.removeScene(props.scene),
  onSuccess: (snapshot) => {
    client.setQueryData(keys.host.settings(), snapshot)
    toast.success(t('groups.settings.remove.done', { name: groupLabel(props.scene) }))
    void router.push({ name: 'groups' })
  },
  onError: (error) =>
    toast.error(t('groups.settings.remove.failed'), { detail: describeError(error, t('ui.error.network')).message }),
  onSettled: () => void readHostState(),
})
async function ask() {
  const confirmed = await confirm({
    title: t('groups.settings.remove.title', { name: groupLabel(props.scene) }),
    message: t('groups.settings.remove.message'),
    confirmLabel: t('groups.settings.remove.action'),
    tone: 'danger',
  })
  if (confirmed) remove.mutate()
}
</script>

<template>
  <FormSection :title="t('groups.settings.remove.section')" :columns="1">
    <div>
      <Button variant="danger-ghost" :icon="Trash2" :loading="remove.isPending.value" @click="ask">
        {{ t('groups.settings.remove.action') }}
      </Button>
    </div>
  </FormSection>
</template>
