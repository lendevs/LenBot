<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ArrowUpCircle, Check, CircleCheck, LoaderCircle, RefreshCw } from '@lucide/vue'
import { keys } from '../../api/query'
import { systemApi, type PluginUpdateResult, type UpdateState } from '../../api/system'
import { ApiError } from '../../api/client'
import { readUpdates } from '../../api/hostStore'
import { formatBytes, formatDateTime } from '../../i18n/format'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import MarkdownText from '../../ui/MarkdownText.vue'
import Skeleton from '../../ui/Skeleton.vue'
import Switch from '../../ui/Switch.vue'
import PluginUpdatesSection from '../plugins/PluginUpdatesSection.vue'
import SnapshotsSection from './SnapshotsSection.vue'

const { t } = useI18n()
const queryClient = useQueryClient()
const current = useQuery({
  queryKey: keys.system.updates(),
  queryFn: ({ signal }) => systemApi.updates(signal),
})
const data = computed(() => current.data.value)
const check = computed(() => data.value?.check)
const operation = computed(() => data.value?.operation)
const offered = computed(() =>
  Boolean(data.value?.managed && check.value?.update_available && check.value.latest),
)
// Asks GitHub: on request, or at once when a newer version is known.
const releases = useQuery({
  queryKey: keys.system.releases(),
  queryFn: ({ signal }) => systemApi.releases(signal),
  enabled: offered,
  staleTime: Infinity,
})
const prerelease = ref(false)
const visible = computed(() =>
  (releases.data.value ?? []).filter((item) => prerelease.value || !item.prerelease),
)
// Notes open with "# LenBot <version>", which the version heading already shows.
const notesBody = (notes: string) => notes.replace(/^#\s[^\n]*\n+/, '')
const target = computed(
  () => releases.data.value?.find((item) => item.version === check.value?.latest) ?? null,
)
const summary = computed(() => {
  const value = check.value
  if (!value) return ''
  if (value.error) return t('system.updates.checkFailed')
  if (value.checked_at)
    return value.latest_prerelease
      ? t('system.updates.latestWithPre', { version: value.latest_prerelease })
      : t('system.updates.latest')
  return value.enabled ? t('system.updates.notChecked') : t('system.updates.checkOff')
})
async function checkNow() {
  await releases.refetch()
  void current.refetch()
  void readUpdates()
}

/** The steps of one update; the host downloads and installs, the launcher does the rest while it restarts. */
const STEPS = ['download', 'install', 'restart'] as const
const restarting = ref(false)
const busy = computed(
  () => restarting.value || ['download', 'install', 'restart'].includes(operation.value?.stage ?? ''),
)
const stepState = (step: (typeof STEPS)[number]) => {
  const at = restarting.value ? 2 : STEPS.indexOf(operation.value?.stage as (typeof STEPS)[number])
  const index = STEPS.indexOf(step)
  return index < at ? 'done' : index === at ? 'active' : 'waiting'
}
const percent = computed(() => {
  const value = operation.value?.progress
  return value && value.total ? Math.min(100, Math.round((value.done / value.total) * 100)) : 0
})

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
let stopped = false
onBeforeUnmount(() => (stopped = true))

/** The host stops while the launcher switches; its public readiness answers again once a version runs. */
async function hostReady(): Promise<boolean> {
  try {
    const response = await fetch('/api/host/ready', {
      cache: 'no-store',
      credentials: 'omit',
      signal: AbortSignal.timeout(3000),
    })
    return response.ok && (await response.json()).ready
  } catch {
    return false
  }
}

let following = false
async function follow() {
  if (following) return
  following = true
  try {
    while (!stopped) {
      await sleep(restarting.value ? 2000 : 800)
      if (restarting.value) {
        if (await hostReady()) {
          // The new version, or the previous one after a rollback; the reloaded page shows which.
          location.reload()
          return
        }
        continue
      }
      let value: UpdateState
      try {
        value = await systemApi.updates()
      } catch (error) {
        if (error instanceof ApiError && error.status === 0) restarting.value = true
        else throw error
        continue
      }
      queryClient.setQueryData(keys.system.updates(), value)
      if (value.operation.stage === 'restart') restarting.value = true
      else if (!['download', 'install'].includes(value.operation.stage)) return
    }
  } finally {
    following = false
  }
}

const withPlugins = ref(true)
const start = useMutation({
  mutationFn: (tag: string) => systemApi.startUpdate(tag, withPlugins.value),
  onSuccess: (value) => {
    queryClient.setQueryData(keys.system.updates(), value)
    void follow()
  },
})
// A page opened during an update keeps showing it.
watch(
  () => operation.value?.stage,
  (stage) => {
    if (stage && ['download', 'install', 'restart'].includes(stage)) void follow()
  },
  { immediate: true },
)
function restartingNow() {
  restarting.value = true
  void follow()
}

const result = computed(() => data.value?.result ?? null)
const pluginResults = computed(() =>
  Array.isArray(result.value?.plugins) ? (result.value.plugins as PluginUpdateResult[]) : [],
)
const pluginFailures = computed(() => pluginResults.value.filter((item) => item.error))
</script>

<template>
  <Skeleton v-if="current.isPending.value" :lines="5" />
  <ErrorNote
    v-else-if="current.isError.value && !restarting"
    :title="t('system.updates.readFailed')"
    :error="current.error.value"
    :retry="current.refetch"
  />
  <div v-else-if="data" class="flex min-w-0 flex-col gap-4">
    <section
      class="flex min-w-0 flex-col gap-4 rounded-xl border p-5"
      :class="offered || busy ? 'border-brand/40 bg-brand-soft' : 'border-line bg-surface'"
    >
      <div class="flex flex-wrap items-center justify-between gap-4">
        <div class="flex flex-col gap-0.5">
          <span class="text-sm text-muted">{{ t('system.updates.current') }}</span>
          <strong class="text-2xl font-semibold text-ink tabular">v{{ data.version }}</strong>
        </div>
        <div v-if="offered && !busy" class="flex flex-wrap items-center gap-4">
          <Field :label="t('system.updates.withPlugins')" inline>
            <Switch v-model="withPlugins" />
          </Field>
          <Button
            variant="primary"
            :icon="ArrowUpCircle"
            :loading="start.isPending.value"
            @click="start.mutate(`v${check!.latest}`)"
          >
            {{ t('system.updates.updateTo', { version: check!.latest }) }}
          </Button>
        </div>
        <div v-else-if="!busy" class="flex flex-wrap items-center gap-3 text-sm text-ink-2">
          <span class="inline-flex items-center gap-1.5">
            <CircleCheck
              v-if="!check?.error && check?.checked_at"
              class="size-4 text-success"
              aria-hidden="true"
            />
            {{ summary }}
          </span>
          <span v-if="check?.checked_at" class="text-muted">{{ formatDateTime(check.checked_at) }}</span>
          <Button size="sm" :icon="RefreshCw" :loading="releases.isFetching.value" @click="checkNow">
            {{ t('system.updates.check') }}
          </Button>
        </div>
      </div>

      <ol v-if="busy" class="flex list-none flex-col gap-3" aria-live="polite">
        <li
          v-for="step in STEPS"
          :key="step"
          class="flex flex-col gap-2 text-sm"
          :class="{
            'text-ink': stepState(step) === 'done',
            'font-semibold text-primary': stepState(step) === 'active',
            'text-muted': stepState(step) === 'waiting',
          }"
        >
          <span class="flex items-center gap-2.5">
            <Check v-if="stepState(step) === 'done'" class="size-4 text-success" aria-hidden="true" />
            <LoaderCircle
              v-else-if="stepState(step) === 'active'"
              class="size-4 animate-spin"
              aria-hidden="true"
            />
            <span v-else class="mx-1 size-2 rounded-full bg-subtle" aria-hidden="true" />
            {{ t(`system.updates.stages.${step}`, { version: operation?.target ?? check?.latest }) }}
            <span
              v-if="step === 'download' && stepState(step) === 'active' && operation?.progress"
              class="font-normal text-muted tabular"
            >
              {{ formatBytes(operation.progress.done) }} / {{ formatBytes(operation.progress.total) }} ·
              {{ percent }}%
            </span>
          </span>
          <span
            v-if="step === 'download' && stepState(step) === 'active'"
            class="ml-6.5 h-1.5 overflow-hidden rounded-full bg-fill"
            role="progressbar"
            :aria-valuenow="percent"
            aria-valuemin="0"
            aria-valuemax="100"
          >
            <span
              class="block h-full rounded-full bg-brand transition-[width] duration-300"
              :style="{ width: `${percent}%` }"
            />
          </span>
        </li>
      </ol>

      <ErrorNote
        v-if="operation?.stage === 'failed' && operation.error && !busy"
        :title="t('system.updates.failed', { version: operation.target })"
        :error="operation.error"
      />
      <ErrorNote
        v-if="start.isError.value"
        :title="t('system.updates.startFailed')"
        :error="start.error.value"
      />
      <ErrorNote v-if="check?.error && !busy" :title="t('system.updates.checkFailed')" :error="check.error" />

      <template v-if="result && !busy">
        <p
          v-if="result.status === 'complete'"
          class="flex flex-wrap items-center gap-2 text-sm font-medium text-success"
        >
          <Check class="size-4" aria-hidden="true" />
          {{
            result.action === 'restore'
              ? t('system.updates.restored', { version: result.to })
              : t('system.updates.updated', { from: result.from, version: result.to })
          }}
          <span class="font-normal text-muted">{{ formatDateTime(result.finished_at) }}</span>
          <span
            v-if="result.plugins === 'pending'"
            class="inline-flex items-center gap-1.5 font-normal text-muted"
          >
            <LoaderCircle class="size-3.5 animate-spin" aria-hidden="true" />
            {{ t('system.updates.pluginsPending') }}
          </span>
          <span v-else-if="pluginResults.length && !pluginFailures.length" class="font-normal text-muted">
            {{ t('system.updates.pluginsDone', { n: pluginResults.length }, pluginResults.length) }}
          </span>
        </p>
        <ErrorNote
          v-else
          :title="
            result.status === 'rolled_back'
              ? t('system.updates.rolledBack', { version: result.to, from: result.from })
              : t('system.updates.failed', { version: result.to })
          "
          :error="result.error ?? ''"
        />
        <ErrorNote
          v-if="pluginFailures.length"
          :title="t('system.updates.pluginsFailed')"
          :error="pluginFailures.map((item) => `${item.name}: ${item.error}`).join('\n')"
        />
      </template>

      <MarkdownText
        v-if="offered && !busy && target"
        :text="notesBody(target.notes)"
        class="border-t border-brand/20 pt-4 text-sm text-ink-2"
      />
      <p v-if="!data.managed" class="text-sm text-ink-2">{{ t('system.updates.source') }}</p>
    </section>

    <PluginUpdatesSection :busy="busy" />
    <SnapshotsSection v-if="data.managed" :items="data.snapshots" :busy="busy" @restarting="restartingNow" />

    <section class="flex min-w-0 flex-col gap-3 rounded-xl border border-line bg-surface p-5">
      <header class="flex flex-wrap items-center justify-between gap-3">
        <h3 class="text-base font-semibold">{{ t('system.updates.releases') }}</h3>
        <Field :label="t('system.updates.prerelease')" inline>
          <Switch v-model="prerelease" />
        </Field>
      </header>
      <ErrorNote
        v-if="releases.isError.value"
        :title="t('system.updates.releasesFailed')"
        :error="releases.error.value"
      />
      <Button
        v-if="!releases.data.value && !releases.isFetching.value"
        class="self-start"
        size="sm"
        :icon="RefreshCw"
        @click="checkNow"
      >
        {{ t('system.updates.showReleases') }}
      </Button>
      <p v-if="releases.data.value && !visible.length" class="text-sm text-muted">
        {{ t('system.updates.none') }}
      </p>
      <ol v-if="visible.length" class="flex list-none flex-col divide-y divide-line">
        <li v-for="item in visible" :key="item.tag" class="flex flex-col gap-2 py-4 first:pt-1">
          <h4 class="flex flex-wrap items-center gap-2 text-sm font-semibold text-ink">
            {{ item.tag }}
            <Badge v-if="item.newer" tone="brand">{{ t('system.updates.newer') }}</Badge>
            <Badge v-if="item.version === data.version">{{ t('system.updates.installed') }}</Badge>
            <Badge v-if="item.prerelease" tone="warning">{{ t('system.updates.pre') }}</Badge>
          </h4>
          <MarkdownText :text="notesBody(item.notes)" class="text-sm text-ink-2" />
        </li>
      </ol>
    </section>
  </div>
</template>
