<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { Globe } from '@lucide/vue'
import { tasksApi, type TaskDetail } from '../../../api/tasks'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import { toast } from '../../../ui/toast'
import { finished } from './labels'

const props = defineProps<{
  scene: string
  task: TaskDetail['task']
  browser: TaskDetail['browser']
  configured: boolean
}>()
const emit = defineEmits<{ changed: []; files: [] }>()

const { t } = useI18n()
const binding = computed(() => props.browser.binding as { browser_instance_id?: string; session_id?: string } | null)
const accountState = computed(() => {
  if (props.task.browser_active) return props.task.browser_session ? 'using' : 'waiting'
  return binding.value ? 'ended' : 'none'
})
const canClose = computed(
  () => props.configured && finished(props.task.status) && props.task.browser_active && Boolean(props.task.browser_session),
)

const status = useMutation({ mutationFn: () => tasksApi.browserStatus(props.scene, props.task.id) })
const close = useMutation({
  mutationFn: () => tasksApi.closeEnvironment(props.scene, props.task.id),
  onSuccess: () => {
    status.reset()
    toast.success(t('groups.tasks.browser.closed'))
    emit('changed')
  },
})
</script>

<template>
  <section class="flex flex-col gap-2">
    <h3 class="flex items-center gap-2 text-sm font-medium text-ink">
      <Globe :size="16" class="text-subtle" aria-hidden="true" />
      {{ t(task.account_browser ? 'groups.tasks.browser.account' : 'groups.tasks.browser.public') }}
    </h3>
    <template v-if="task.account_browser">
      <p class="text-sm text-ink-2">{{ t(`groups.tasks.browser.${accountState}`) }}</p>
      <p v-if="binding" class="font-mono text-xs break-all text-muted">
        {{ t('groups.tasks.browser.binding', { device: binding.browser_instance_id, session: binding.session_id }) }}
      </p>
      <div v-if="task.browser_active || canClose" class="flex flex-wrap gap-2">
        <Button v-if="task.browser_active" size="sm" :loading="status.isPending.value" @click="status.mutate()">
          {{ t('groups.tasks.browser.check') }}
        </Button>
        <Button v-if="canClose" size="sm" :loading="close.isPending.value" @click="close.mutate()">
          {{ t('groups.tasks.browser.close') }}
        </Button>
      </div>
      <p v-if="task.browser_active && status.data.value" class="text-sm text-ink-2">
        {{ t(status.data.value.browser ? 'groups.tasks.browser.online' : 'groups.tasks.browser.offline') }} ·
        {{ t(status.data.value.session ? 'groups.tasks.browser.sessionFound' : 'groups.tasks.browser.sessionMissing') }}
        <template v-if="status.data.value.session?.agent_window_id">
          · {{ t('groups.tasks.browser.window', { id: status.data.value.session.agent_window_id }) }}
        </template>
      </p>
    </template>
    <p v-else class="text-sm text-ink-2">
      {{ t(browser.public_enabled ? 'groups.tasks.browser.publicOn' : 'groups.tasks.browser.publicOff') }}
      <template v-if="task.container">{{ t('groups.tasks.browser.container') }}</template>
    </p>
    <Button v-if="configured && browser.output_count" size="sm" variant="ghost" class="self-start" @click="emit('files')">
      {{ t('groups.tasks.browser.files', { n: browser.output_count }) }}
    </Button>
    <ErrorNote v-if="status.isError.value" :title="t('groups.tasks.browser.statusFailed')" :error="status.error.value" />
    <ErrorNote v-if="close.isError.value" :title="t('groups.tasks.browser.closeFailed')" :error="close.error.value" />
  </section>
</template>
