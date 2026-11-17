<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Box, ChevronDown, ShieldAlert, ShieldCheck, Wrench } from '@lucide/vue'
import type { PluginsSnapshot } from '../../../api/plugins'
import { developerDetails } from '../../../composables/useDeveloperMode'
import { formatDateTime } from '../../../i18n/format'
import { groupLabel } from '../../../layouts/shell/scenes'
import Badge from '../../../ui/Badge.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import RawRecord from '../../groups/tasks/RawRecord.vue'
import { isolationOf, manifestOf, permissionsOf, runningOf, sceneSecondaryId } from '../view'

const props = defineProps<{ name: string; snapshot: PluginsSnapshot }>()

const { t } = useI18n()
const running = computed(() => runningOf(props.snapshot, props.name))
const known = computed(() => Boolean(running.value || manifestOf(props.snapshot, props.name)))
const permissions = computed(() => permissionsOf(props.snapshot, props.name))
const isolation = computed(() => isolationOf(props.snapshot, props.name))
const empty = computed(() => {
  const value = running.value
  return (
    Boolean(value) &&
    !value!.commands.length &&
    !value!.rules.length &&
    !value!.tools.length &&
    !value!.crons.length &&
    !value!.notices.length
  )
})
</script>

<template>
  <div class="flex min-w-0 max-w-4xl flex-col divide-y divide-line">
    <section v-if="known" class="flex flex-col gap-4 py-6 first:pt-1 last:pb-0">
      <div class="flex items-start gap-3">
        <component
          :is="permissions === null ? ShieldAlert : ShieldCheck"
          :size="18"
          class="mt-0.5 shrink-0"
          :class="permissions === null ? 'text-warning' : 'text-success'"
          aria-hidden="true"
        />
        <div class="flex min-w-0 flex-col gap-1.5">
          <h3 class="text-sm font-semibold text-ink">{{ t('plugins.permissions.title') }}</h3>
          <p v-if="permissions === null" class="text-sm text-muted">
            {{ t('plugins.permissions.undeclared') }}
          </p>
          <p v-else-if="!permissions.length" class="text-sm text-muted">
            {{ t('plugins.permissions.none') }}
          </p>
          <div v-else class="flex flex-wrap gap-1.5">
            <Badge v-for="item in permissions" :key="item.name" size="md">{{ item.title }}</Badge>
          </div>
        </div>
      </div>
      <div class="flex items-start gap-3">
        <Box :size="18" class="mt-0.5 shrink-0 text-subtle" aria-hidden="true" />
        <div class="flex min-w-0 flex-col gap-1">
          <h3 class="text-sm font-semibold text-ink">{{ t(`plugins.isolation.${isolation}`) }}</h3>
          <p class="text-sm text-muted">{{ t(`plugins.isolation.${isolation}Detail`) }}</p>
        </div>
      </div>
    </section>

    <div v-if="!running" class="py-6">
      <EmptyState :icon="Wrench" :title="t('plugins.tools.notRunning')" compact />
    </div>
    <template v-else>
      <section
        v-if="running.commands.length || running.rules.length"
        class="flex flex-col gap-3 py-6 first:pt-1 last:pb-0"
      >
        <h3 class="text-base font-semibold text-ink">{{ t('plugins.tools.commands') }}</h3>
        <ul class="flex list-none flex-col divide-y divide-line">
          <li
            v-for="item in running.commands"
            :key="item.name"
            class="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2.5 first:pt-0 last:pb-0"
          >
            <code class="rounded-sm bg-fill px-1.5 py-0.5 font-mono text-sm text-ink">/{{ item.name }}</code>
            <span class="min-w-0 text-sm text-ink-2">{{ item.description }}</span>
          </li>
          <li
            v-for="item in running.rules"
            :key="`${item.kind}:${item.pattern}`"
            class="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2.5 first:pt-0 last:pb-0"
          >
            <Badge>{{ t(`plugins.tools.rule.${item.kind}`) }}</Badge>
            <code class="min-w-0 rounded-sm bg-fill px-1.5 py-0.5 font-mono text-sm break-all text-ink">
              {{ item.pattern }}
            </code>
            <span class="min-w-0 text-sm text-ink-2">{{ item.description }}</span>
          </li>
        </ul>
      </section>

      <section v-if="running.tools.length" class="flex flex-col gap-3 py-6 first:pt-1 last:pb-0">
        <h3 class="text-base font-semibold text-ink">{{ t('plugins.tools.modelTools') }}</h3>
        <ul class="flex list-none flex-col divide-y divide-line">
          <li
            v-for="item in running.tools"
            :key="item.name"
            class="flex flex-col gap-1.5 py-2.5 first:pt-0 last:pb-0"
          >
            <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <code class="rounded-sm bg-fill px-1.5 py-0.5 font-mono text-sm text-ink">{{ item.name }}</code>
              <span class="min-w-0 text-sm text-ink-2">{{ item.summary }}</span>
              <Badge v-if="item.needs_source" tone="info">{{ t('plugins.tools.needsSource') }}</Badge>
            </div>
            <details class="group">
              <summary
                class="inline-flex cursor-pointer list-none items-center gap-1 rounded-sm text-xs font-medium text-muted transition-colors select-none hover:text-ink focus-visible:focus-ring [&::-webkit-details-marker]:hidden"
              >
                {{ t('plugins.tools.details') }}
                <ChevronDown
                  :size="14"
                  class="transition-transform group-open:rotate-180"
                  aria-hidden="true"
                />
              </summary>
              <div class="mt-2 flex flex-col gap-2">
                <p class="text-sm whitespace-pre-wrap text-ink-2">{{ item.description }}</p>
                <CodeBlock :code="item.parameters" :max-lines="12" :label="t('plugins.tools.parameters')" />
              </div>
            </details>
          </li>
        </ul>
      </section>

      <section v-if="running.crons.length" class="flex flex-col gap-3 py-6 first:pt-1 last:pb-0">
        <h3 class="text-base font-semibold text-ink">{{ t('plugins.tools.crons') }}</h3>
        <ul class="flex list-none flex-col divide-y divide-line">
          <li
            v-for="job in running.crons"
            :key="`${job.scene}:${job.name}`"
            class="flex flex-col gap-1.5 py-2.5 first:pt-0 last:pb-0"
          >
            <p class="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-sm text-ink">
              <strong class="font-medium">{{ job.name }}</strong>
              <span class="text-subtle">·</span>
              <span>{{ groupLabel(job.scene) }}</span>
              <span v-if="sceneSecondaryId(job.scene)" class="font-mono text-xs text-muted tabular">
                {{ sceneSecondaryId(job.scene) }}
              </span>
            </p>
            <p class="text-xs text-muted tabular">
              <code class="font-mono">{{ job.expression }}</code>
              · {{ job.timezone }}
              <template v-if="job.next_run">
                · {{ t('plugins.tools.next', { time: formatDateTime(job.next_run) }) }}
              </template>
            </p>
            <ErrorNote v-if="job.last_error" :title="t('plugins.tools.cronFailed')" :error="job.last_error" />
          </li>
        </ul>
      </section>

      <section v-if="running.notices.length" class="flex flex-col gap-3 py-6 first:pt-1 last:pb-0">
        <h3 class="text-base font-semibold text-ink">{{ t('plugins.tools.notices') }}</h3>
        <div class="flex flex-wrap gap-1.5">
          <code
            v-for="notice in running.notices"
            :key="notice"
            class="rounded-full bg-fill px-2.5 py-0.5 font-mono text-xs font-medium text-muted"
          >
            {{ notice }}
          </code>
        </div>
      </section>

      <div v-if="empty" class="py-6">
        <EmptyState :icon="Wrench" :title="t('plugins.tools.none')" compact />
      </div>
      <div v-if="developerDetails && running.instructions" class="py-4">
        <RawRecord :label="t('plugins.tools.instructions')" :code="running.instructions" />
      </div>
    </template>
  </div>
</template>
