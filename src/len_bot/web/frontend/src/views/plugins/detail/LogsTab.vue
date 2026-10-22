<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { ArrowUpRight, ScrollText } from '@lucide/vue'
import type { RunningPlugin } from '../../../api/plugins'
import { developerDetails } from '../../../composables/useDeveloperMode'
import { formatDateTime, formatRelative } from '../../../i18n/format'
import { groupLabel } from '../../../layouts/shell/scenes'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import RawRecord from '../../groups/tasks/RawRecord.vue'

defineProps<{ name: string; running: RunningPlugin | null }>()

const { t } = useI18n()
function every(seconds: number) {
  if (seconds % 3600 === 0) return t('plugins.logs.everyHours', { n: seconds / 3600 }, seconds / 3600)
  if (seconds % 60 === 0) return t('plugins.logs.everyMinutes', { n: seconds / 60 }, seconds / 60)
  return t('plugins.logs.everySeconds', { n: seconds }, seconds)
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
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
    <template v-else>
      <section
        v-if="running.backgrounds.length"
        class="flex flex-col gap-3 rounded-xl border border-line bg-surface p-5"
      >
        <h3 class="text-base font-semibold">{{ t('plugins.logs.backgrounds') }}</h3>
        <ul class="flex list-none flex-col divide-y divide-line">
          <li
            v-for="item in running.backgrounds"
            :key="item.method"
            class="flex flex-col gap-1.5 py-2.5 first:pt-0 last:pb-0"
          >
            <p class="flex flex-wrap items-baseline gap-x-3 text-sm">
              <code class="rounded-sm bg-fill px-1.5 py-0.5 font-mono">{{ item.method }}</code>
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

      <section class="flex flex-col gap-3 rounded-xl border border-line bg-surface p-5">
        <h3 class="text-base font-semibold">{{ t('plugins.logs.errors') }}</h3>
        <ul v-if="running.errors.length" class="flex list-none flex-col divide-y divide-line">
          <li
            v-for="(item, index) in running.errors"
            :key="index"
            class="flex flex-col gap-1.5 py-2.5 first:pt-0 last:pb-0"
          >
            <p class="flex flex-wrap items-center gap-2 text-xs text-muted">
              <span class="tabular">{{ formatDateTime(item.at, { withSeconds: true }) }}</span>
              <Badge class="font-mono">{{ item.where }}</Badge>
            </p>
            <CodeBlock :code="item.error" :max-lines="8" />
          </li>
        </ul>
        <p v-else class="text-sm text-muted">{{ t('plugins.logs.noErrors') }}</p>
      </section>

      <section
        v-if="running.model_calls.length"
        class="flex flex-col gap-3 rounded-xl border border-line bg-surface p-5"
      >
        <h3 class="text-base font-semibold">{{ t('plugins.logs.calls') }}</h3>
        <ul class="flex list-none flex-col divide-y divide-line">
          <li
            v-for="call in running.model_calls"
            :key="call.id"
            class="flex flex-col gap-1.5 py-2.5 first:pt-0 last:pb-0"
          >
            <p class="flex flex-wrap items-center gap-2 text-sm">
              <span class="text-xs text-muted tabular">{{ formatDateTime(call.started) }}</span>
              <span class="text-ink-2">{{ groupLabel(call.scene) }}</span>
              <Badge :tone="call.ended === null ? 'info' : call.error ? 'error' : 'success'" dot>
                {{
                  t(`plugins.logs.call.${call.ended === null ? 'running' : call.error ? 'failed' : 'done'}`)
                }}
              </Badge>
            </p>
            <ErrorNote v-if="call.error" :title="t('plugins.logs.callFailed')" :error="call.error" />
            <RawRecord
              v-if="developerDetails"
              :label="t('plugins.logs.usage')"
              :code="{ usage: call.usage, tokens: call.tokens }"
            />
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
