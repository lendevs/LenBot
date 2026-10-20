<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { ExternalLink } from '@lucide/vue'
import { setupApi } from '../../../api/setup'
import Badge from '../../../ui/Badge.vue'
import Checkbox from '../../../ui/Checkbox.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { useWizard } from '../wizard'

const { t } = useI18n()
const { draft } = useWizard()
const plugins = useQuery({ queryKey: ['setup', 'plugins'], queryFn: setupApi.plugins })

function toggle(name: string, on: boolean | 'indeterminate') {
  draft.plugins = on === true ? [...new Set([...draft.plugins, name])] : draft.plugins.filter((item) => item !== name)
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <p class="text-sm text-muted">{{ t('setup.plugins.disabled') }}</p>
    <Skeleton v-if="plugins.isPending.value" :lines="4" />
    <ErrorNote
      v-else-if="plugins.isError.value"
      :title="t('setup.plugins.readFailed')"
      :error="plugins.error.value"
      :retry="plugins.refetch"
    />
    <EmptyState v-else-if="!plugins.data.value?.plugins.length" :title="t('setup.plugins.none')" />
    <ul v-else class="flex flex-col divide-y divide-line rounded-xl border border-line bg-surface">
      <li v-for="item in plugins.data.value.plugins" :key="item.name" class="flex gap-3 px-4 py-3.5">
        <Checkbox
          :model-value="draft.plugins.includes(item.name)"
          :aria-label="item.title"
          @update:model-value="(on) => toggle(item.name, on)"
        />
        <div class="flex min-w-0 flex-1 flex-col gap-1">
          <div class="flex min-w-0 flex-wrap items-center gap-2">
            <span class="font-medium text-ink">{{ item.title }}</span>
            <Badge v-if="item.installed">{{ t('setup.plugins.installed') }}</Badge>
            <a
              :href="item.repository"
              target="_blank"
              rel="noopener noreferrer"
              class="inline-flex items-center gap-1 rounded-sm text-xs text-muted hover:text-ink focus-visible:focus-ring"
            >
              {{ item.version }}
              <ExternalLink :size="12" aria-hidden="true" />
            </a>
          </div>
          <p class="text-sm text-ink-2">{{ item.description }}</p>
          <p v-if="item.capabilities.length" class="text-xs text-muted">{{ item.capabilities.join(' · ') }}</p>
          <p v-if="item.error" class="text-xs break-words text-error">
            {{ t('setup.plugins.lastError', { error: item.error }) }}
          </p>
        </div>
      </li>
    </ul>
  </div>
</template>
