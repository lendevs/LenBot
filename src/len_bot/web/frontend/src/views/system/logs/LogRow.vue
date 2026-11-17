<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpRight, ChevronDown, Copy } from '@lucide/vue'
import type { LogRecord } from '../../../api/logs'
import { formatDateTime } from '../../../i18n/format'
import { groupLabel } from '../../../layouts/shell/scenes'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import IconButton from '../../../ui/IconButton.vue'
import { toast } from '../../../ui/toast'
import { sceneSecondaryId } from '../draft'
import { idFields, seconds, severity, useLogLabels } from './labels'

const props = defineProps<{ item: LogRecord; timeZone?: string; turn?: string }>()
const emit = defineEmits<{ filter: [key: 'turn' | 'plugin' | 'task' | 'scene', value: string] }>()

const { t } = useI18n()
const labels = useLogLabels()
const open = ref(false)
const tone = computed(() => severity(props.item))
const title = computed(() => labels.title(props.item))
/** The message says more than the event name when both are present. */
const detail = computed(() =>
  props.item.event && props.item.message && props.item.message !== props.item.event ? props.item.message : '',
)
const ids = computed(() =>
  idFields
    .filter((key) => props.item[key] !== undefined && props.item[key] !== null)
    .map((key) => ({ key, value: String(props.item[key]) })),
)
const filterOf = { turn_id: 'turn', plugin: 'plugin', task_id: 'task' } as const
/** A failed model call names the provider and role whose settings fix it. */
const provider = computed(() =>
  props.item.event === 'model_call' &&
  props.item.status === 'failed' &&
  typeof props.item.provider === 'string'
    ? props.item.provider
    : null,
)
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
    class="group relative flex min-w-0 flex-col gap-1 border-b border-l-2 border-b-line py-2.5 pr-2.5 pl-3 transition-colors hover:bg-hover/40"
    :class="
      tone === 'error'
        ? 'border-l-error bg-error-bg/35'
        : tone === 'warning'
          ? 'border-l-warning bg-warning-bg/25'
          : 'border-l-transparent'
    "
  >
    <div class="flex min-w-0 items-start gap-1.5">
      <button
        type="button"
        class="flex min-w-0 flex-1 cursor-pointer flex-wrap items-center gap-x-2 gap-y-1 rounded-sm text-left focus-visible:focus-ring"
        :aria-expanded="open"
        @click="open = !open"
      >
        <span class="shrink-0 font-mono text-xs text-muted tabular">
          {{ formatDateTime(seconds(item), { withSeconds: true, timeZone }) }}
        </span>
        <Badge v-if="tone === 'error' || tone === 'warning'" :tone="tone">
          {{ item.level || (tone === 'error' ? 'ERROR' : 'WARNING') }}
        </Badge>
        <strong
          class="min-w-0 truncate text-sm font-medium"
          :class="tone === 'error' ? 'text-error' : 'text-ink'"
        >
          {{ title }}
        </strong>
        <span class="min-w-0 truncate font-mono text-xs text-subtle">{{ item.source }}</span>
      </button>
      <span
        class="inline-flex shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100 pointer-coarse:opacity-100"
      >
        <IconButton :icon="Copy" :label="t('logs.copy')" size="sm" variant="ghost" @click="copy" />
      </span>
      <ChevronDown
        :size="15"
        class="mt-1.5 shrink-0 text-subtle transition-transform"
        :class="open && 'rotate-180'"
        aria-hidden="true"
      />
    </div>
    <p v-if="detail" class="min-w-0 text-sm break-words text-ink-2" :class="!open && 'line-clamp-2'">
      {{ detail }}
    </p>
    <p v-if="item.scene || ids.length" class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
      <button
        v-if="item.scene"
        type="button"
        class="inline-flex cursor-pointer items-baseline gap-1 rounded-sm hover:text-ink focus-visible:focus-ring"
        @click="emit('filter', 'scene', item.scene)"
      >
        <span class="font-medium text-ink-2">{{ groupLabel(item.scene) }}</span>
        <span v-if="sceneSecondaryId(item.scene)" class="font-mono text-subtle tabular">
          {{ sceneSecondaryId(item.scene) }}
        </span>
      </button>
      <template v-for="{ key, value } in ids" :key="key">
        <button
          v-if="key in filterOf && !(key === 'turn_id' && value === turn)"
          type="button"
          class="cursor-pointer rounded-sm font-mono tabular hover:text-ink focus-visible:focus-ring"
          @click="emit('filter', filterOf[key as keyof typeof filterOf], value)"
        >
          {{ t(`logs.ids.${key}`) }} {{ key === 'turn_id' ? value.slice(0, 8) : value }}
        </button>
        <span v-else class="font-mono tabular">
          {{ t(`logs.ids.${key}`) }} {{ key === 'turn_id' ? value.slice(0, 8) : value }}
        </span>
      </template>
    </p>
    <p v-if="errorText" class="min-w-0 text-sm break-words text-error" :class="!open && 'line-clamp-3'">
      {{ errorText }}
    </p>
    <div v-if="provider" class="flex flex-wrap gap-2">
      <Button
        size="sm"
        variant="ghost"
        :icon-right="ArrowUpRight"
        :to="{ name: 'host-models', query: { tab: 'providers', item: provider } }"
      >
        {{ t('logs.toProvider', { name: provider }) }}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        :icon-right="ArrowUpRight"
        :to="{ name: 'host-models', query: { tab: 'roles' } }"
      >
        {{ t('logs.toRoles') }}
      </Button>
    </div>
    <div v-if="open" class="mt-1 min-w-0 max-w-full">
      <CodeBlock :code="item" :max-lines="24" />
    </div>
  </div>
</template>
