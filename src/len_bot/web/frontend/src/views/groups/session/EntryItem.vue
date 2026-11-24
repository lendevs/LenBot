<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Brain, ChevronDown, ChevronRight, Ear, Inbox, Settings2, Wrench } from '@lucide/vue'
import type { EntryToolCall, SessionEntry } from '../../../api/session'
import { formatDateTime } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import type { Tone } from '../../../ui/Badge.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import TimelineItem from '../../../ui/TimelineItem.vue'
import { useLiveLabels } from '../live/labels'

const USER_PREVIEW_LINES = 8
const USER_PREVIEW_CHARS = 480

const props = defineProps<{
  entry: SessionEntry
  /** Tool results of the loaded entries by call id, shown under the call that asked for them. */
  results: Map<string, SessionEntry>
  timeZone: string
  /** Show the stored entry as it is. */
  raw: boolean
  last: boolean
  /** True while a turn is currently running in this scene. */
  running?: boolean
}>()

const { t, te } = useI18n()
const labels = useLiveLabels()
const message = computed(() => props.entry.message)
const roles: Record<string, { icon: typeof Brain; tone: Tone }> = {
  user: { icon: Inbox, tone: 'neutral' },
  assistant: { icon: Brain, tone: 'info' },
  tool: { icon: Wrench, tone: 'neutral' },
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
  if (listened.value && typeof value === 'string') {
    // Strip only paired Markdown emphasis and a single outer [label] wrapper, leaving other brackets and ** intact.
    const trimmed = value.trim()
    const unwrapped = /^\[[^[\]]+\]$/.test(trimmed) ? trimmed.slice(1, -1).trim() : trimmed
    return unwrapped.replace(/\*\*([^*\n]+?)\*\*/g, '$1').trim() || null
  }
  return value
})

const isPlainUser = computed(() => message.value.role === 'user' && typeof content.value === 'string')
const userText = computed(() => (isPlainUser.value ? (content.value as string) : ''))
const userLines = computed(() => (isPlainUser.value ? userText.value.split('\n') : []))
const userHasExtraLines = computed(() => userLines.value.length > USER_PREVIEW_LINES)
const userClamped = computed(() => !userHasExtraLines.value && userText.value.length > USER_PREVIEW_CHARS)
const userHead = computed(() =>
  userHasExtraLines.value ? userLines.value.slice(0, USER_PREVIEW_LINES).join('\n') : userText.value,
)
const userTail = computed(() =>
  userHasExtraLines.value ? userLines.value.slice(USER_PREVIEW_LINES).join('\n') : '',
)
const textExpanded = ref(false)
watch(
  () => props.entry.seq,
  () => {
    textExpanded.value = false
  },
)

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
const callPending = (call: EntryToolCall) =>
  !props.results.has(call.id) && Boolean(props.running) && props.last && props.entry.active
/** Only warn about a missing tool result once newer entries exist after this call (not while running or at the page tail). */
const callMissingResult = (call: EntryToolCall) => !props.results.has(call.id) && !props.last
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
        <div v-else-if="isPlainUser" class="rounded-md bg-fill/70 px-3.5 py-2.5 text-ink">
          <div
            class="text-sm leading-6 break-words whitespace-pre-wrap"
            :class="userClamped && !textExpanded && 'line-clamp-8'"
            :style="
              userHasExtraLines && !textExpanded
                ? { maskImage: 'linear-gradient(to bottom, black calc(100% - 28px), transparent)' }
                : undefined
            "
          >
            {{ userHead }}
          </div>
          <div
            v-if="userHasExtraLines"
            class="ui-grid-collapse"
            :data-open="textExpanded ? 'true' : 'false'"
            :inert="!textExpanded"
            :aria-hidden="!textExpanded || undefined"
          >
            <div>
              <div class="text-sm leading-6 break-words whitespace-pre-wrap">{{ userTail }}</div>
            </div>
          </div>
          <button
            v-if="userHasExtraLines || userClamped"
            type="button"
            class="mt-1.5 inline-flex cursor-pointer items-center gap-1 rounded-sm text-xs font-medium text-muted transition-colors hover:text-ink focus-visible:focus-ring pointer-coarse:min-h-8"
            :aria-expanded="textExpanded"
            @click="textExpanded = !textExpanded"
          >
            <ChevronDown
              :size="14"
              class="transition-transform duration-(--dur-1) ease-out"
              :class="textExpanded && 'rotate-180'"
              aria-hidden="true"
            />
            <span class="tabular">
              {{
                textExpanded
                  ? t('common.collapse')
                  : userHasExtraLines
                    ? t('ui.code.expand', { n: userLines.length })
                    : t('common.expand')
              }}
            </span>
          </button>
        </div>
        <CodeBlock v-else :code="content" :max-lines="10" />
      </template>
      <div
        v-for="call in calls"
        :key="call.id"
        class="flex flex-col gap-1.5 border-l-2 border-line-strong pl-3"
      >
        <div class="flex flex-wrap items-center gap-2">
          <strong class="text-sm font-medium text-ink">{{ labels.tool(call.function.name) }}</strong>
          <Badge v-if="callPending(call)" tone="info" dot pulse>
            {{ t('groups.live.step.toolStatus.pending') }}
          </Badge>
          <Badge v-else-if="callMissingResult(call)" tone="warning">{{ t('groups.session.noResult') }}</Badge>
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
      <details v-if="raw" class="group">
        <summary
          class="inline-flex cursor-pointer list-none items-center gap-1 rounded-sm text-xs font-medium text-muted select-none hover:text-ink focus-visible:focus-ring [&::-webkit-details-marker]:hidden"
        >
          <ChevronRight
            :size="13"
            class="shrink-0 text-subtle transition-transform duration-150 group-open:rotate-90"
            aria-hidden="true"
          />
          {{ t('groups.session.raw') }}
        </summary>
        <div class="mt-1.5">
          <CodeBlock :code="entry" :max-lines="12" />
        </div>
      </details>
    </div>
  </TimelineItem>
</template>
