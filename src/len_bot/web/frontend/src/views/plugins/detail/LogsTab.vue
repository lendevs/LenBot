<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpRight, ScrollText } from '@lucide/vue'
import type { PluginCall, RunningPlugin } from '../../../api/plugins'
import { developerDetails } from '../../../composables/useDeveloperMode'
import { formatCompact, formatDateTime, formatDuration, formatRelative } from '../../../i18n/format'
import { groupLabel } from '../../../layouts/shell/scenes'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Select from '../../../ui/Select.vue'
import Switch from '../../../ui/Switch.vue'
import { useLiveLabels } from '../../groups/live/labels'
import RawRecord from '../../groups/tasks/RawRecord.vue'
import { sceneSecondaryId } from '../view'

const props = defineProps<{ name: string; running: RunningPlugin | null }>()

const { t } = useI18n()
const labels = useLiveLabels()

function every(seconds: number) {
  if (seconds % 3600 === 0) return t('plugins.logs.everyHours', { n: seconds / 3600 }, seconds / 3600)
  if (seconds % 60 === 0) return t('plugins.logs.everyMinutes', { n: seconds / 60 }, seconds / 60)
  return t('plugins.logs.everySeconds', { n: seconds }, seconds)
}

function tokenInfo(value: unknown): { input: number; output: number } | null {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  if (typeof record.input !== 'number' || typeof record.output !== 'number') return null
  return { input: record.input, output: record.output }
}

function callMetrics(call: PluginCall): string {
  const parts = [labels.role(call.role)]
  if (call.ended !== null) parts.push(formatDuration(Math.max(0, call.ended - call.started) * 1000))
  const tokens = tokenInfo(call.tokens)
  if (tokens) {
    parts.push(
      t('plugins.logs.tokens', {
        input: formatCompact(tokens.input),
        output: formatCompact(tokens.output),
      }),
    )
  }
  return parts.join(' · ')
}

const ALL = '*'
const selectedScene = ref(ALL)
const onlyErrors = ref(false)
const calls = computed(() => props.running?.model_calls ?? [])
const showFilters = computed(() => calls.value.length > 5)
const sceneOptions = computed(() => {
  const unique = [...new Set(calls.value.map((call) => call.scene))]
  return [
    { value: ALL, label: t('plugins.logs.allGroups') },
    ...unique.map((scene) => ({ value: scene, label: groupLabel(scene) })),
  ]
})
watch(sceneOptions, (options) => {
  if (selectedScene.value !== ALL && !options.some((option) => option.value === selectedScene.value)) {
    selectedScene.value = ALL
  }
})
const filteredCalls = computed(() => {
  if (!showFilters.value) return calls.value
  return calls.value.filter(
    (call) =>
      (selectedScene.value === ALL || call.scene === selectedScene.value) &&
      (!onlyErrors.value || Boolean(call.error)),
  )
})
</script>

<template>
  <div class="flex min-w-0 max-w-4xl flex-col gap-4">
    <div class="flex justify-end">
      <Button
        size="sm"
        variant="ghost"
        :icon-right="ArrowUpRight"
        :to="{ name: 'host-logs', query: { tab: 'system', plugin: name } }"
      >
        {{ t('plugins.logs.open') }}
      </Button>
    </div>
    <EmptyState v-if="!running" :icon="ScrollText" :title="t('plugins.logs.notRunning')" compact />
    <div v-else class="flex min-w-0 flex-col divide-y divide-line">
      <section v-if="running.backgrounds.length" class="flex flex-col gap-3 py-5 first:pt-0 last:pb-0">
        <h3 class="text-base font-semibold text-ink">{{ t('plugins.logs.backgrounds') }}</h3>
        <ul class="flex list-none flex-col divide-y divide-line">
          <li
            v-for="item in running.backgrounds"
            :key="item.method"
            class="flex flex-col gap-1.5 py-2.5 first:pt-0 last:pb-0"
          >
            <p class="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm tabular">
              <code class="rounded-sm bg-fill px-1.5 py-0.5 font-mono text-ink">{{ item.method }}</code>
              <span class="text-ink-2">{{ every(item.every_seconds) }}</span>
              <span class="text-xs text-muted">
                {{
                  item.last_finished
                    ? t('plugins.logs.finished', { time: formatRelative(item.last_finished) })
                    : item.last_started
                      ? t('plugins.logs.started', { time: formatRelative(item.last_started) })
                      : t('plugins.logs.never')
                }}
              </span>
            </p>
            <ErrorNote
              v-if="item.last_error"
              :title="t('plugins.logs.backgroundFailed')"
              :error="item.last_error"
            />
          </li>
        </ul>
      </section>

      <section class="flex flex-col gap-3 py-5 first:pt-0 last:pb-0">
        <h3 class="text-base font-semibold text-ink">{{ t('plugins.logs.errors') }}</h3>
        <ul v-if="running.errors.length" class="flex list-none flex-col divide-y divide-line">
          <li
            v-for="(item, index) in running.errors"
            :key="index"
            class="flex flex-col gap-1.5 py-2.5 first:pt-0 last:pb-0"
          >
            <p class="flex flex-wrap items-center gap-2 text-xs text-muted">
              <span class="tabular">{{ formatDateTime(item.at, { withSeconds: true }) }}</span>
              <code class="rounded-full bg-fill px-2 py-0.5 font-mono text-xs text-muted">
                {{ item.where }}
              </code>
            </p>
            <CodeBlock :code="item.error" :max-lines="8" />
          </li>
        </ul>
        <p v-else class="text-sm text-muted">{{ t('plugins.logs.noErrors') }}</p>
      </section>

      <section v-if="calls.length" class="flex flex-col gap-3 py-5 first:pt-0 last:pb-0">
        <div class="flex flex-wrap items-center gap-3">
          <h3 class="mr-auto text-base font-semibold text-ink">{{ t('plugins.logs.calls') }}</h3>
          <template v-if="showFilters">
            <div class="w-44">
              <Select v-model="selectedScene" :options="sceneOptions" size="sm" />
            </div>
            <Switch v-model="onlyErrors" size="sm">
              <span class="text-sm text-ink-2">{{ t('plugins.logs.onlyErrors') }}</span>
            </Switch>
          </template>
        </div>
        <p v-if="!filteredCalls.length" class="text-sm text-muted">{{ t('common.noResults') }}</p>
        <ul v-else class="flex list-none flex-col divide-y divide-line">
          <li
            v-for="call in filteredCalls"
            :key="call.id"
            class="flex flex-col gap-1.5 py-2.5 first:pt-0 last:pb-0"
          >
            <div class="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm tabular">
              <span class="text-xs text-muted">{{ formatDateTime(call.started) }}</span>
              <span class="font-medium text-ink">{{ groupLabel(call.scene) }}</span>
              <span v-if="sceneSecondaryId(call.scene)" class="font-mono text-xs text-muted">
                {{ sceneSecondaryId(call.scene) }}
              </span>
              <Badge :tone="call.ended === null ? 'info' : call.error ? 'error' : 'success'" dot>
                {{
                  t(`plugins.logs.call.${call.ended === null ? 'running' : call.error ? 'failed' : 'done'}`)
                }}
              </Badge>
              <span class="text-xs text-muted">{{ callMetrics(call) }}</span>
            </div>
            <ErrorNote v-if="call.error" :title="t('plugins.logs.callFailed')" :error="call.error" />
            <RawRecord
              v-if="developerDetails"
              :label="t('plugins.logs.usage')"
              :code="{ usage: call.usage, tokens: call.tokens }"
            />
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>
