<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { ChevronRight } from '@lucide/vue'
import { keys } from '../../../api/query'
import { tasksApi, type TaskEvent, type TaskEventPreview } from '../../../api/tasks'
import { developerDetails } from '../../../composables/useDeveloperMode'
import { formatDateTime } from '../../../i18n/format'
import CodeBlock from '../../../ui/CodeBlock.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import RawRecord from './RawRecord.vue'

const props = defineProps<{
  scene: string
  taskId: number
  event: TaskEventPreview
  timeZone: string
  open: boolean
}>()
const emit = defineEmits<{ toggle: [] }>()

const { t, te } = useI18n()
const label = computed(() => {
  const type = props.event.event_type ?? props.event.kind
  const key = `groups.tasks.events.types.${type}`
  return te(key) ? t(key) : type
})
const full = useQuery({
  queryKey: computed(() => keys.tasks.event(props.scene, props.taskId, props.event.id)),
  queryFn: () => tasksApi.event(props.scene, props.taskId, props.event.id),
  enabled: computed(() => props.open),
  staleTime: Infinity,
})

type Part = { type: 'text'; text: string } | { type: 'image'; mimeType: string; data: string }
const IMAGES = ['image/png', 'image/jpeg', 'image/webp']
/** The readable parts of an event: its text fields and the text and images of a message or tool result. */
function parts(record: TaskEvent): Part[] {
  const body = record.body
  const found: Part[] = ['text', 'title', 'message', 'value', 'note', 'summary']
    .filter((key) => typeof body[key] === 'string')
    .map((key) => ({ type: 'text', text: body[key] as string }))
  if (Array.isArray(body.options))
    found.push({ type: 'text', text: t('groups.tasks.events.options', { options: body.options.join('、') }) })
  if (typeof body.confirmed === 'boolean')
    found.push({
      type: 'text',
      text: t(body.confirmed ? 'groups.tasks.events.agreed' : 'groups.tasks.events.refused'),
    })
  const nested =
    body.type === 'tool_execution_end' ? body.result : body.type === 'message_end' ? body.message : null
  const content = (nested as { content?: unknown } | null)?.content
  if (Array.isArray(content)) {
    for (const part of content as Record<string, unknown>[]) {
      if (part.type === 'text' && typeof part.text === 'string') found.push({ type: 'text', text: part.text })
      else if (
        part.type === 'image' &&
        IMAGES.includes(part.mimeType as string) &&
        typeof part.data === 'string'
      )
        found.push({ type: 'image', mimeType: part.mimeType as string, data: part.data })
    }
  }
  return found
}
const shown = computed(() => (full.data.value ? parts(full.data.value) : []))
const error = computed(() => {
  const value = full.data.value?.body.error
  return value === undefined || value === null ? null : String(value)
})
</script>

<template>
  <li>
    <button
      type="button"
      class="flex w-full cursor-pointer items-baseline gap-3 rounded-sm px-1 py-2 text-left text-sm hover:bg-hover focus-visible:focus-ring"
      :aria-expanded="open"
      @click="emit('toggle')"
    >
      <ChevronRight
        :size="14"
        class="shrink-0 self-center text-subtle transition-transform"
        :class="open && 'rotate-90'"
        aria-hidden="true"
      />
      <span class="w-24 shrink-0 text-xs text-muted tabular">
        {{ formatDateTime(event.created, { timeZone, withSeconds: true }) }}
      </span>
      <span class="shrink-0 text-ink">
        {{ label }}
        <template v-if="event.tool_name">
          ·
          <span class="font-mono text-xs">{{ event.tool_name }}</span>
        </template>
      </span>
    </button>
    <div v-if="open" class="flex flex-col gap-2 pb-3 pl-6 sm:pl-[8.75rem]">
      <Skeleton v-if="full.isPending.value" :lines="2" />
      <ErrorNote
        v-else-if="full.isError.value"
        :title="t('groups.tasks.events.readFailed')"
        :error="full.error.value"
        :retry="full.refetch"
      />
      <template v-else-if="full.data.value">
        <template v-for="(part, index) in shown" :key="index">
          <CodeBlock v-if="part.type === 'text'" :code="part.text" wrap :max-lines="20" />
          <img
            v-else
            :src="`data:${part.mimeType};base64,${part.data}`"
            :alt="t('groups.tasks.events.image')"
            loading="lazy"
            class="h-auto max-w-full rounded-lg border border-line"
          />
        </template>
        <ErrorNote v-if="error" :title="t('groups.tasks.events.stepError')" :error="error" />
        <p v-if="!shown.length && !error && !developerDetails" class="text-xs text-muted">
          {{ t('groups.tasks.events.noText') }}
        </p>
        <RawRecord v-if="developerDetails" :label="t('groups.tasks.events.raw')" :code="full.data.value" />
      </template>
    </div>
  </li>
</template>
