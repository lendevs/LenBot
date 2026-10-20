<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { BookOpen, Brain, CircleAlert } from '@lucide/vue'
import type { ModelStep, Step, ToolDetail, TurnDetail } from '../../../api/timeline'
import { formatCompact, formatDuration } from '../../../i18n/format'
import Badge, { type Tone } from '../../../ui/Badge.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Timeline from '../../../ui/Timeline.vue'
import TimelineItem from '../../../ui/TimelineItem.vue'
import { useLiveLabels } from './labels'

const props = defineProps<{ detail: TurnDetail }>()

const { t } = useI18n()
const labels = useLiveLabels()
const running = () => props.detail.turn.ended === null

const toolTones: Record<ToolDetail['status'], Tone> = {
  pending: 'info',
  complete: 'success',
  error: 'error',
  interrupted: 'warning',
}

function modelMeta(model: ModelStep): string {
  const parts = [labels.role(model.role)]
  if (model.ended !== null) parts.push(formatDuration((model.ended - model.started) * 1000))
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
const stepRunning = (step: Step) =>
  running() && (step.models.some((model) => model.ended === null) || step.tools.some((tool) => tool.status === 'pending'))
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
        :meta="detail.recall.length ? t('groups.live.step.recallCount', { n: detail.recall.length }) : undefined"
        :last="!detail.steps.length"
      >
        <p v-if="!detail.recall.length" class="text-muted">{{ t('groups.live.step.recallNone') }}</p>
        <ul v-else class="flex flex-col gap-1">
          <li v-for="item in detail.recall" :key="`${item.scope}:${item.path}:${item.content.length}`">
            <details class="group">
              <summary class="cursor-pointer truncate font-mono text-xs text-ink-2 hover:text-ink">
                {{ item.scope }} · {{ item.path }}
              </summary>
              <CodeBlock :code="item.content" :max-lines="8" class="mt-1" />
            </details>
          </li>
        </ul>
      </TimelineItem>
      <TimelineItem
        v-for="(step, index) in detail.steps"
        :key="step.step"
        :title="t('groups.live.step.title', { n: step.step })"
        :icon="stepFailed(step) ? CircleAlert : Brain"
        :tone="stepFailed(step) ? 'error' : 'brand'"
        :running="stepRunning(step)"
        :last="index === detail.steps.length - 1"
      >
        <div class="flex flex-col gap-2.5">
          <p v-for="model in step.models" :key="model.id" class="text-xs text-subtle tabular">
            {{ modelMeta(model) }}
          </p>
          <template v-for="model in step.models" :key="`e${model.id}`">
            <ErrorNote v-if="model.error" :title="t('groups.live.step.failed')" :error="model.error" />
            <p v-if="model.snapshot_expired_at" class="text-xs text-muted">{{ t('groups.live.step.expired') }}</p>
          </template>
          <details v-if="step.thoughts.length" class="rounded-md bg-fill px-3 py-2">
            <summary class="cursor-pointer text-xs font-medium text-muted">{{ t('groups.live.step.thoughts') }}</summary>
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
            class="flex flex-col gap-1.5 border-l-2 border-line-strong pl-3"
          >
            <div class="flex flex-wrap items-center gap-2">
              <strong class="text-sm font-medium text-ink">{{ labels.tool(tool.name) }}</strong>
              <Badge :tone="toolTones[tool.status]">{{ t(`groups.live.step.toolStatus.${tool.status}`) }}</Badge>
            </div>
            <CodeBlock
              v-if="Object.keys(tool.arguments).length"
              :code="tool.arguments"
              :max-lines="8"
              :label="t('groups.live.step.arguments')"
            />
            <CodeBlock v-if="tool.result" :code="tool.result" :max-lines="8" :label="t('groups.live.step.result')" />
          </div>
        </div>
      </TimelineItem>
    </Timeline>
  </div>
</template>
