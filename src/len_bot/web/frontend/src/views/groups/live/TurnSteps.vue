<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { BookOpen, Brain, ChevronRight, CircleAlert } from '@lucide/vue'
import type { ModelStep, Step, ToolDetail, TurnDetail } from '../../../api/timeline'
import { formatCompact, formatDuration } from '../../../i18n/format'
import Badge, { type Tone } from '../../../ui/Badge.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Timeline from '../../../ui/Timeline.vue'
import TimelineItem from '../../../ui/TimelineItem.vue'
import { useLiveLabels } from './labels'
import StickerCandidates from './StickerCandidates.vue'

const LARGE_CHAR_THRESHOLD = 1024
const LARGE_LINE_THRESHOLD = 12

const props = defineProps<{ detail: TurnDetail }>()

const { t } = useI18n()
const labels = useLiveLabels()
const running = () => props.detail.turn.ended === null
const openBlocks = ref(new Set<string>())

function onToggle(key: string, event: Event) {
  const isOpen = (event.currentTarget as HTMLDetailsElement).open
  const next = new Set(openBlocks.value)
  if (isOpen) next.add(key)
  else next.delete(key)
  openBlocks.value = next
}

function hasManyLines(text: string, limit: number): boolean {
  let count = 1
  for (let i = 0; i < text.length; i++) {
    if (text.charCodeAt(i) === 10 && ++count > limit) return true
  }
  return false
}

/** Fast early-exit size check so huge objects are not JSON-stringified just to decide whether to fold. */
function isLargePayload(value: unknown): boolean {
  if (typeof value === 'string') {
    return value.length > LARGE_CHAR_THRESHOLD || hasManyLines(value, LARGE_LINE_THRESHOLD)
  }
  let budget = LARGE_CHAR_THRESHOLD
  const stack: unknown[] = [value]
  while (stack.length > 0 && budget > 0) {
    const current = stack.pop()
    if (typeof current === 'string') {
      if (hasManyLines(current, LARGE_LINE_THRESHOLD)) return true
      budget -= current.length + 2
    } else if (Array.isArray(current)) {
      budget -= current.length * 4
      for (const item of current) stack.push(item)
    } else if (current && typeof current === 'object') {
      const entries = Object.entries(current as Record<string, unknown>)
      budget -= entries.length * 6
      for (const [k, v] of entries) {
        budget -= k.length
        stack.push(v)
      }
    } else {
      budget -= 8
    }
  }
  return budget <= 0
}

const toolTones: Record<ToolDetail['status'], Tone> = {
  pending: 'info',
  complete: 'success',
  error: 'error',
  interrupted: 'warning',
}

function modelMeta(model: ModelStep): string {
  const parts = [labels.role(model.role)]
  if (model.ended !== null) parts.push(formatDuration((model.ended - model.started) * 1000))
  if (model.retries) parts.push(t('groups.live.step.retries', { n: model.retries }))
  if (model.tokens) {
    parts.push(
      t('groups.live.turn.tokens', {
        input: formatCompact(model.tokens.input),
        output: formatCompact(model.tokens.output),
      }),
    )
  }
  return parts.join(' · ')
}
// The candidate number a later say or react in this turn sent from a react preview.
function chosenCandidate(tool: ToolDetail): number | null {
  const tools = props.detail.steps.flatMap((step) => step.tools)
  for (const later of tools.slice(tools.indexOf(tool) + 1)) {
    if (later.name === 'react' && later.arguments.preview === true) return null
    const choice =
      later.name === 'say'
        ? (later.arguments.sticker as Record<string, unknown> | undefined)
        : later.arguments
    if (
      (later.name === 'react' || later.name === 'say') &&
      later.status === 'complete' &&
      typeof choice?.candidate === 'number'
    )
      return choice.candidate
  }
  return null
}
const stepRunning = (step: Step) =>
  running() &&
  (step.models.some((model) => model.ended === null) || step.tools.some((tool) => tool.status === 'pending'))
const stepFailed = (step: Step) =>
  step.models.some((model) => model.error) || step.tools.some((tool) => tool.status === 'error')
</script>

<template>
  <div class="flex flex-col gap-3">
    <ErrorNote v-if="detail.turn.error" :title="t('groups.live.turn.failed')" :error="detail.turn.error" />
    <p v-if="!detail.steps.length && detail.recall === null" class="text-sm text-muted">
      {{ t('groups.live.turn.noModel') }}
    </p>
    <Timeline>
      <TimelineItem
        v-if="detail.recall !== null"
        :title="t('groups.live.step.recall')"
        :icon="BookOpen"
        tone="info"
        :meta="
          detail.recall.length ? t('groups.live.step.recallCount', { n: detail.recall.length }) : undefined
        "
        :last="!detail.steps.length"
      >
        <p v-if="!detail.recall.length" class="text-muted">{{ t('groups.live.step.recallNone') }}</p>
        <ul v-else class="flex flex-col gap-1">
          <li v-for="item in detail.recall" :key="`${item.scope}:${item.path}:${item.content.length}`">
            <details
              class="group"
              @toggle="onToggle(`recall:${item.scope}:${item.path}:${item.content.length}`, $event)"
            >
              <summary
                class="flex cursor-pointer list-none items-center gap-1 rounded-sm font-mono text-xs text-ink-2 select-none hover:text-ink focus-visible:focus-ring [&::-webkit-details-marker]:hidden"
              >
                <ChevronRight
                  :size="13"
                  class="shrink-0 text-subtle transition-transform duration-150 group-open:rotate-90"
                  aria-hidden="true"
                />
                <span class="truncate">{{ item.scope }} · {{ item.path }}</span>
              </summary>
              <div
                v-if="openBlocks.has(`recall:${item.scope}:${item.path}:${item.content.length}`)"
                class="mt-1.5"
              >
                <CodeBlock :code="item.content" :max-lines="8" />
              </div>
            </details>
          </li>
        </ul>
      </TimelineItem>
      <TimelineItem
        v-for="(step, index) in detail.steps"
        :key="step.step"
        :title="t('groups.live.step.title', { n: step.step })"
        :icon="stepFailed(step) ? CircleAlert : Brain"
        :tone="stepFailed(step) ? 'error' : stepRunning(step) ? 'info' : 'neutral'"
        :running="stepRunning(step)"
        :last="index === detail.steps.length - 1"
      >
        <template v-if="step.models.length === 1" #meta>
          <span class="min-w-0 truncate text-xs text-subtle tabular">{{ modelMeta(step.models[0]!) }}</span>
        </template>
        <div class="flex flex-col gap-2.5">
          <template v-if="step.models.length > 1">
            <p v-for="model in step.models" :key="model.id" class="text-xs text-subtle tabular">
              {{ modelMeta(model) }}
            </p>
          </template>
          <template v-for="model in step.models" :key="`e${model.id}`">
            <ErrorNote v-if="model.error" :title="t('groups.live.step.failed')" :error="model.error" />
            <p v-if="model.snapshot_expired_at" class="text-xs text-muted">
              {{ t('groups.live.step.expired') }}
            </p>
          </template>
          <details v-if="step.thoughts.length" class="group rounded-md bg-fill px-3 py-2">
            <summary
              class="flex cursor-pointer list-none items-center gap-1 rounded-sm text-xs font-medium text-muted select-none hover:text-ink focus-visible:focus-ring [&::-webkit-details-marker]:hidden"
            >
              <ChevronRight
                :size="13"
                class="shrink-0 text-subtle transition-transform duration-150 group-open:rotate-90"
                aria-hidden="true"
              />
              {{ t('groups.live.step.thoughts') }}
            </summary>
            <p
              v-for="(thought, n) in step.thoughts"
              :key="n"
              class="mt-1.5 text-sm break-words whitespace-pre-wrap text-ink-2"
            >
              {{ thought }}
            </p>
          </details>
          <p v-if="step.text" class="text-sm break-words whitespace-pre-wrap text-ink">{{ step.text }}</p>
          <div
            v-for="tool in step.tools"
            :key="tool.call_id"
            class="flex flex-col gap-1.5 border-l-2 pl-3"
            :class="
              tool.status === 'error'
                ? 'border-error/50'
                : tool.status === 'pending'
                  ? 'border-info/50'
                  : 'border-line-strong'
            "
          >
            <div class="flex flex-wrap items-center gap-2">
              <strong class="text-sm font-medium text-ink">{{ labels.tool(tool.name) }}</strong>
              <Badge :tone="toolTones[tool.status]">
                {{ t(`groups.live.step.toolStatus.${tool.status}`) }}
              </Badge>
            </div>
            <template v-if="Object.keys(tool.arguments).length">
              <details
                v-if="isLargePayload(tool.arguments)"
                class="group"
                @toggle="onToggle(`arg:${step.step}:${tool.call_id}`, $event)"
              >
                <summary
                  class="inline-flex cursor-pointer list-none items-center gap-1 rounded-sm text-xs font-medium text-muted select-none hover:text-ink focus-visible:focus-ring [&::-webkit-details-marker]:hidden"
                >
                  <ChevronRight
                    :size="13"
                    class="shrink-0 text-subtle transition-transform duration-150 group-open:rotate-90"
                    aria-hidden="true"
                  />
                  {{ t('groups.live.step.arguments') }}
                </summary>
                <CodeBlock
                  v-if="openBlocks.has(`arg:${step.step}:${tool.call_id}`)"
                  :code="tool.arguments"
                  :max-lines="8"
                  class="mt-1.5"
                />
              </details>
              <CodeBlock
                v-else
                :code="tool.arguments"
                :max-lines="8"
                :label="t('groups.live.step.arguments')"
              />
            </template>
            <StickerCandidates
              v-if="tool.name === 'react' && tool.arguments.preview === true && tool.result"
              :result="tool.result"
              :chosen="chosenCandidate(tool)"
            />
            <template v-if="tool.result">
              <details
                v-if="isLargePayload(tool.result)"
                class="group"
                @toggle="onToggle(`res:${step.step}:${tool.call_id}`, $event)"
              >
                <summary
                  class="inline-flex cursor-pointer list-none items-center gap-1 rounded-sm text-xs font-medium text-muted select-none hover:text-ink focus-visible:focus-ring [&::-webkit-details-marker]:hidden"
                >
                  <ChevronRight
                    :size="13"
                    class="shrink-0 text-subtle transition-transform duration-150 group-open:rotate-90"
                    aria-hidden="true"
                  />
                  {{ t('groups.live.step.result') }}
                </summary>
                <CodeBlock
                  v-if="openBlocks.has(`res:${step.step}:${tool.call_id}`)"
                  :code="tool.result"
                  :max-lines="8"
                  class="mt-1.5"
                />
              </details>
              <CodeBlock v-else :code="tool.result" :max-lines="8" :label="t('groups.live.step.result')" />
            </template>
          </div>
        </div>
      </TimelineItem>
    </Timeline>
  </div>
</template>
