<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Globe } from '@lucide/vue'
import type { TaskDetail } from '../../../api/tasks'
import Button from '../../../ui/Button.vue'

defineProps<{
  task: TaskDetail['task']
  browser: TaskDetail['browser']
  configured: boolean
}>()
const emit = defineEmits<{ files: [] }>()

const { t } = useI18n()
</script>

<template>
  <section class="flex flex-col gap-2">
    <h3 class="flex items-center gap-2 text-sm font-medium text-ink">
      <Globe :size="16" class="text-subtle" aria-hidden="true" />
      {{ t('groups.tasks.browser.public') }}
    </h3>
    <p class="text-sm text-ink-2">
      {{ t(browser.public_enabled ? 'groups.tasks.browser.publicOn' : 'groups.tasks.browser.publicOff') }}
      <template v-if="task.container">{{ t('groups.tasks.browser.container') }}</template>
    </p>
    <Button
      v-if="configured && browser.output_count"
      size="sm"
      variant="ghost"
      class="self-start"
      @click="emit('files')"
    >
      {{ t('groups.tasks.browser.files', { n: browser.output_count }) }}
    </Button>
  </section>
</template>
