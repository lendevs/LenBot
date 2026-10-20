<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown, Copy } from '@lucide/vue'
import type { LogRecord } from '../../../api/logs'
import { formatDateTime } from '../../../i18n/format'
import { groupLabel } from '../../../layouts/shell/scenes'
import CodeBlock from '../../../ui/CodeBlock.vue'
import IconButton from '../../../ui/IconButton.vue'
import { toast } from '../../../ui/toast'
import { idFields, seconds, severity, useLogLabels } from './labels'

const props = defineProps<{ item: LogRecord; timeZone?: string; turn?: string }>()
const emit = defineEmits<{ filter: [key: 'turn' | 'plugin' | 'task' | 'scene', value: string] }>()

const { t } = useI18n()
const labels = useLogLabels()
const open = ref(false)
const tone = computed(() => severity(props.item))
const title = computed(() => labels.title(props.item))
/** The message says more than the event name when both are present. */
const detail = computed(() => (props.item.event && props.item.message && props.item.message !== props.item.event ? props.item.message : ''))
const ids = computed(() =>
  idFields
    .filter((key) => props.item[key] !== undefined && props.item[key] !== null)
    .map((key) => ({ key, value: String(props.item[key]) })),
)
const filterOf = { turn_id: 'turn', plugin: 'plugin', task_id: 'task' } as const
const errorText = computed(() => {
  const error = props.item.error
  return error ? (error.type ? `${error.type}: ${error.message}` : error.message) : ''
})

async function copy() {
  try {
    await navigator.clipboard.writeText(JSON.stringify(props.item, null, 2))
    toast.success(t('logs.copied'))
  } catch {
    toast.error(t('logs.copyFailed'))
  }
}
</script>

<template>
  <div
    class="group relative flex min-w-0 flex-col gap-1 border-b border-l-[3px] border-b-line py-2.5 pr-2 pl-3"
    :class="tone === 'error' ? 'border-l-error bg-error-bg/40' : tone === 'warning' ? 'border-l-warning' : 'border-l-transparent'"
  >
    <div class="flex min-w-0 items-start gap-2">
      <button
        type="button"
        class="flex min-w-0 flex-1 cursor-pointer flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-sm text-left focus-visible:focus-ring"
        :aria-expanded="open"
        @click="open = !open"
      >
        <strong class="min-w-0 truncate text-sm font-medium" :class="tone === 'error' ? 'text-error' : 'text-ink'">{{ title }}</strong>
        <span class="text-xs text-muted tabular">{{ formatDateTime(seconds(item), { withSeconds: true, timeZone }) }}</span>
        <span class="min-w-0 truncate font-mono text-xs text-subtle">{{ item.source }}</span>
      </button>
      <IconButton :icon="Copy" :label="t('logs.copy')" size="sm" variant="ghost" class="opacity-0 group-hover:opacity-100 focus-visible:opacity-100" @click="copy" />
      <ChevronDown :size="15" class="mt-1 shrink-0 text-subtle transition-transform" :class="open && 'rotate-180'" aria-hidden="true" />
    </div>
    <p v-if="detail" class="text-sm break-words text-ink-2" :class="!open && 'line-clamp-2'">{{ detail }}</p>
    <p v-if="item.scene || ids.length" class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
      <button v-if="item.scene" type="button" class="cursor-pointer rounded-sm hover:text-ink focus-visible:focus-ring" @click="emit('filter', 'scene', item.scene)">
        {{ groupLabel(item.scene) }}
      </button>
      <template v-for="{ key, value } in ids" :key="key">
        <button
          v-if="key in filterOf && !(key === 'turn_id' && value === turn)"
          type="button"
          class="cursor-pointer rounded-sm font-mono hover:text-ink focus-visible:focus-ring"
          @click="emit('filter', filterOf[key as keyof typeof filterOf], value)"
        >
          {{ t(`logs.ids.${key}`) }} {{ key === 'turn_id' ? value.slice(0, 8) : value }}
        </button>
        <span v-else class="font-mono">{{ t(`logs.ids.${key}`) }} {{ key === 'turn_id' ? value.slice(0, 8) : value }}</span>
      </template>
    </p>
    <p v-if="errorText" class="text-sm break-words text-error" :class="!open && 'line-clamp-3'">{{ errorText }}</p>
    <CodeBlock v-if="open" :code="item" :max-lines="24" class="mt-1" />
  </div>
</template>
