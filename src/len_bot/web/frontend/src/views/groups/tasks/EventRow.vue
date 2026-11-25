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
/** The readable parts of an event: its text fields, tool arguments, and message/tool result parts. */
function parts(record: TaskEvent): Part[] {
  const body = record.body
  const found: Part[] = ['text', 'title', 'message', 'value', 'note', 'summary']
    .filter((key) => typeof body[key] === 'string')
    .map((key) => ({ type: 'text', text: body[key] as string }))
  if (body.type === 'tool_execution_start' && body.args !== undefined && body.args !== null) {
    const formatted = typeof body.args === 'string' ? body.args : JSON.stringify(body.args, null, 2)
    if (formatted) found.push({ type: 'text', text: formatted })
  }
  if (Array.isArray(body.options))
    found.push({
      type: 'text',
      text: t('groups.tasks.events.options', {
        options: body.options.join(t('groups.tasks.schedules.cadence.separator')),
      }),
    })
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
  <li class="min-w-0">
    <button
      type="button"
      class="flex w-full min-w-0 cursor-pointer items-baseline gap-2.5 px-2 py-2.5 text-left text-sm transition-colors duration-150 hover:bg-hover focus-visible:focus-ring"
      :aria-expanded="open"
      @click="emit('toggle')"
    >
      <ChevronRight
        :size="14"
        class="shrink-0 self-center text-subtle transition-transform duration-150"
        :class="open && 'rotate-90'"
        aria-hidden="true"
      />
      <span class="shrink-0 text-xs text-muted tabular">
        {{ formatDateTime(event.created, { timeZone, withSeconds: true }) }}
      </span>
      <span class="shrink-0 text-ink">
        {{ label }}
        <template v-if="event.tool_name">
          ·
          <span class="font-mono text-xs text-ink-2">{{ event.tool_name }}</span>
        </template>
      </span>
      <span
        v-if="event.preview"
        class="min-w-0 flex-1 truncate text-right text-xs text-muted"
        :title="event.preview"
      >
        {{ event.preview }}
      </span>
    </button>
    <div class="ui-grid-collapse" :data-open="open ? 'true' : 'false'" :inert="!open">
      <div>
        <div v-if="open || full.data.value" class="flex min-w-0 flex-col gap-2 px-2 pb-3 pl-7">
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
            <RawRecord
              v-if="developerDetails"
              :label="t('groups.tasks.events.raw')"
              :code="full.data.value"
            />
          </template>
        </div>
      </div>
    </div>
  </li>
</template>
