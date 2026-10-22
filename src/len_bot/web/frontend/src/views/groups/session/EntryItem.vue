<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Brain, Ear, Inbox, Settings2, Wrench } from '@lucide/vue'
import type { EntryToolCall, SessionEntry } from '../../../api/session'
import { formatDateTime } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import type { Tone } from '../../../ui/Badge.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import TimelineItem from '../../../ui/TimelineItem.vue'
import { useLiveLabels } from '../live/labels'

const props = defineProps<{
  entry: SessionEntry
  /** Tool results of the loaded entries by call id, shown under the call that asked for them. */
  results: Map<string, SessionEntry>
  timeZone: string
  /** Show the stored entry as it is. */
  raw: boolean
  last: boolean
}>()

const { t, te } = useI18n()
const labels = useLiveLabels()
const message = computed(() => props.entry.message)
const roles: Record<string, { icon: typeof Brain; tone: Tone }> = {
  user: { icon: Inbox, tone: 'neutral' },
  assistant: { icon: Brain, tone: 'brand' },
  tool: { icon: Wrench, tone: 'info' },
  system: { icon: Settings2, tone: 'neutral' },
}
const calls = computed(() => message.value.tool_calls ?? [])
/** A reply without tool calls ends the turn without speaking; its words are the model's own note. */
const listened = computed(() => message.value.role === 'assistant' && !calls.value.length)
const role = computed(() =>
  listened.value ? { icon: Ear, tone: 'neutral' as Tone } : (roles[message.value.role] ?? roles.system),
)
const title = computed(() => {
  if (listened.value) return t('groups.session.listened')
  const key = `groups.session.roles.${message.value.role}`
  return te(key) ? t(key) : message.value.role
})
const content = computed(() => {
  const value = message.value.content
  if (value === undefined || value === null || value === '') return null
  // Notes often come as Markdown; the emphasis marks and bracketed labels are noise here.
  return listened.value && typeof value === 'string'
    ? value.replace(/\*\*|^\[|\]$/g, '').trim() || null
    : value
})

/** Arguments are JSON text written by the model; text that does not parse is shown as it is. */
function argumentsOf(call: EntryToolCall): unknown {
  try {
    const value: unknown = JSON.parse(call.function.arguments)
    return value && typeof value === 'object' && !Object.keys(value).length ? null : value
  } catch {
    return call.function.arguments || null
  }
}
const resultOf = (call: EntryToolCall) => props.results.get(call.id)?.message.content ?? null
</script>

<template>
  <TimelineItem
    :title="title"
    :icon="role.icon"
    :tone="role.tone"
    :last="last"
    :class="!entry.active && 'opacity-60'"
  >
    <template #meta>
      <time v-if="entry.created !== null" class="shrink-0 text-xs text-subtle tabular">
        {{ formatDateTime(entry.created, { timeZone }) }}
      </time>
    </template>
    <div class="flex flex-col gap-2">
      <template v-if="content !== null">
        <p
          v-if="message.role === 'assistant' && typeof content === 'string'"
          class="text-sm break-words whitespace-pre-wrap"
          :class="listened ? 'text-muted' : 'text-ink'"
        >
          {{ content }}
        </p>
        <CodeBlock v-else :code="content" :max-lines="10" />
      </template>
      <div
        v-for="call in calls"
        :key="call.id"
        class="flex flex-col gap-1.5 border-l-2 border-line-strong pl-3"
      >
        <div class="flex flex-wrap items-center gap-2">
          <strong class="text-sm font-medium text-ink">{{ labels.tool(call.function.name) }}</strong>
          <Badge v-if="!results.has(call.id)" tone="warning">{{ t('groups.session.noResult') }}</Badge>
        </div>
        <CodeBlock
          v-if="argumentsOf(call) !== null"
          :code="argumentsOf(call)"
          :max-lines="8"
          :label="t('groups.live.step.arguments')"
        />
        <CodeBlock
          v-if="resultOf(call) !== null"
          :code="resultOf(call)"
          :max-lines="8"
          :label="t('groups.live.step.result')"
        />
      </div>
      <details v-if="raw">
        <summary class="cursor-pointer text-xs font-medium text-muted hover:text-ink">
          {{ t('groups.session.raw') }}
        </summary>
        <CodeBlock :code="entry" :max-lines="12" class="mt-1.5" />
      </details>
    </div>
  </TimelineItem>
</template>
