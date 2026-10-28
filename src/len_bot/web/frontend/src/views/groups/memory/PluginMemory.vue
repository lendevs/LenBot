<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { MemoryPlugin } from '../../../api/memory'
import { formatDateTime } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'

defineProps<{ plugin: MemoryPlugin | null; recap: string | null; timeZone: string }>()

const { t } = useI18n()
/** Plugin host states and their labels; a loaded plugin has not finished starting. */
const labels: Record<string, string> = { failed: 'failed', stopped: 'stopped', loaded: 'starting' }
</script>

<template>
  <dl class="grid gap-x-6 gap-y-2 rounded-lg border border-line px-4 py-3 text-sm sm:grid-cols-[auto_1fr]">
    <template v-if="plugin">
      <dt class="text-muted">{{ t('groups.memory.plugin.memory') }}</dt>
      <dd class="flex flex-wrap items-center gap-2 text-ink">
        {{ t('groups.memory.plugin.name', { name: plugin.name }) }}
        <Badge v-if="plugin.status !== 'running'" tone="error">
          {{
            plugin.status && labels[plugin.status]
              ? t(`plugins.status.${labels[plugin.status]}`)
              : t('groups.memory.plugin.missing')
          }}
        </Badge>
      </dd>
      <dt class="text-muted">{{ t('groups.memory.plugin.progress') }}</dt>
      <dd class="text-ink tabular">
        {{
          plugin.progress?.message_time
            ? formatDateTime(plugin.progress.message_time, { timeZone })
            : t('groups.memory.plugin.unreported')
        }}
      </dd>
      <template v-if="plugin.last_error">
        <dt class="text-muted">{{ t('groups.memory.plugin.lastError') }}</dt>
        <dd class="min-w-0 break-words text-error">
          {{ formatDateTime(plugin.last_error.at, { timeZone }) }} · {{ plugin.last_error.where }} ·
          {{ plugin.last_error.error }}
        </dd>
      </template>
    </template>
    <template v-if="recap">
      <dt class="text-muted">{{ t('groups.memory.plugin.recap') }}</dt>
      <dd class="text-ink">{{ t('groups.memory.plugin.name', { name: recap }) }}</dd>
    </template>
  </dl>
</template>
