<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ArrowUpRight, MoreHorizontal, RefreshCw, RotateCcw, Trash2, Upload } from '@lucide/vue'
import { pluginsApi, type PluginAction, type PluginsSnapshot } from '../../../api/plugins'
import { useUnsavedChanges } from '../../../composables/useUnsavedChanges.js'
import Avatar from '../../../ui/Avatar.vue'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import DropdownMenu, { type MenuEntry } from '../../../ui/DropdownMenu.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import IconButton from '../../../ui/IconButton.vue'
import SaveBar from '../../../ui/SaveBar.vue'
import Tabs from '../../../ui/Tabs.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import type { InstallRequest } from '../InstallDialog.vue'
import { configBody, formProblems, initialDraft, type Draft } from '../schema/config'
import { usePluginsState } from '../state'
import {
  candidateChange,
  configuredIn,
  disabledIn,
  enabledIn,
  featureCount,
  manifestOf,
  permissionsOf,
  runningOf,
  scenesUsing,
  statusOf,
  statusTone,
  versionOf,
} from '../view'
import LogsTab from './LogsTab.vue'
import ScenesTab from './ScenesTab.vue'
import SettingsTab from './SettingsTab.vue'
import SkillsTab from './SkillsTab.vue'
import ToolsTab from './ToolsTab.vue'
import VersionTab from './VersionTab.vue'

const props = defineProps<{ name: string; snapshot: PluginsSnapshot }>()
const emit = defineEmits<{ install: [request: InstallRequest] }>()

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const state = usePluginsState()
const manifest = computed(() => manifestOf(props.snapshot, props.name))
const running = computed(() => runningOf(props.snapshot, props.name))
const source = computed(() => manifest.value?.source ?? null)
const entries = computed(() => props.snapshot.available[props.name] ?? [])
const health = computed(() => state.healthOf(props.name))
const status = computed(() => statusOf(props.snapshot, props.name, health.value))
const enabled = computed(() => enabledIn(props.snapshot, props.name))
const loaded = computed(() => configuredIn(props.snapshot, props.name))
const busy = computed(() => state.busy.value !== null)
const working = computed(() => state.busy.value === props.name)
const version = computed(() => versionOf(props.snapshot, props.name))

// The draft of the settings tab lives here, so the header's enable button saves what is typed.
const fields = computed(() => manifest.value?.fields ?? [])
const saved = computed(() => props.snapshot.saved.plugins[props.name])
const initial = computed(() => initialDraft(fields.value, saved.value))
const draft = ref<Draft>(initial.value)
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
watch(initial, (next, previous) => {
  if (!previous || same(draft.value, previous)) draft.value = next
})
const dirty = computed(() => !same(draft.value, initial.value))
const configured = computed(() =>
  Object.fromEntries(Object.entries(saved.value ?? {}).map(([key, item]) => [key, 'configured' in item && item.configured])),
)
const problems = computed(() => formProblems(fields.value, draft.value, configured.value, t))
const invalid = computed(() => Object.keys(problems.value).length > 0)
// An untouched form does not start out red; errors show once it changes or enabling is tried.
const attempted = ref(false)
const shownProblems = computed(() => (dirty.value || attempted.value ? problems.value : {}))
useUnsavedChanges(dirty, { keep: ['view', 'item', 'part'] })

const saveError = ref<string | null>(null)
watch(draft, () => (saveError.value = null), { deep: true })
async function save() {
  saveError.value = null
  if (invalid.value) {
    attempted.value = true
    tab.value = 'settings'
    saveError.value = Object.values(problems.value)[0]
    return
  }
  let config
  try {
    config = configBody(fields.value, draft.value, saved.value, t)
  } catch (error) {
    saveError.value = (error as Error).message
    return
  }
  const wasOn = enabled.value
  try {
    await state.run(props.name, () => pluginsApi.save(props.name, true, config), {
      quiet: true,
      success: wasOn ? t('common.saved') : t('plugins.detail.enabled'),
    })
    draft.value = initial.value
  } catch (error) {
    saveError.value = describeError(error, t('ui.error.network')).message
  }
}
const disable = () => state.run(props.name, () => pluginsApi.save(props.name, false), { success: t('plugins.detail.disabled') })
async function act(action: PluginAction) {
  const result = await state.run(props.name, () => pluginsApi.act(props.name, action))
  if (!result) return
  const failed = result.running.plugins.some((item) => item.name === props.name && item.status === 'failed')
  if (failed) toast.error(t('plugins.detail.actionFailed'))
  else toast.success(t(`plugins.detail.done.${action}`))
}

async function uninstall() {
  const sure = await confirm({
    title: t('plugins.uninstall.title', { name: props.name }),
    message: t('plugins.uninstall.message'),
    confirmLabel: t('plugins.uninstall.confirm'),
    tone: 'danger',
  })
  if (!sure) return
  const result = await state.run(props.name, () => pluginsApi.uninstall(props.name), { success: t('plugins.uninstall.done') })
  if (result) void router.push({ query: {} })
}
async function removeData() {
  const sure = await confirm({
    title: t('plugins.removeData.title', { name: props.name }),
    message: t('plugins.removeData.message'),
    confirmLabel: t('plugins.removeData.confirm'),
    tone: 'danger',
  })
  if (sure) await state.run(props.name, () => pluginsApi.removeData(props.name), { success: t('plugins.removeData.done') })
}
const update = () => emit('install', { kind: 'update', name: props.name, ref: source.value?.ref ?? null })

const menu = computed<MenuEntry[]>(() => {
  const items: MenuEntry[] = []
  if (loaded.value) items.push({ label: t('plugins.detail.reload'), icon: RefreshCw, disabled: busy.value || dirty.value, select: () => void act('reload') })
  if (source.value?.installed?.kind === 'git')
    items.push({ label: t('plugins.detail.update'), icon: Upload, disabled: busy.value || dirty.value, select: update })
  if (source.value?.previous && !source.value.candidate)
    items.push({ label: t('plugins.version.rollback', { version: source.value.previous.version }), icon: RotateCcw, disabled: busy.value, select: () => void act('rollback') })
  if (manifest.value?.managed || disabledIn(props.snapshot, props.name)) items.push({ type: 'separator' })
  if (manifest.value?.managed)
    items.push({ label: t('plugins.uninstall.confirm'), icon: Trash2, danger: true, disabled: busy.value, select: () => void uninstall() })
  if (disabledIn(props.snapshot, props.name))
    items.push({ label: t('plugins.removeData.confirm'), icon: Trash2, danger: true, disabled: busy.value, select: () => void removeData() })
  return items
})

const change = computed(() => candidateChange(props.snapshot, props.name))
const changeText = computed(() => {
  const parts: string[] = []
  const { permissions, isolation } = change.value
  if (permissions !== undefined)
    parts.push(
      permissions === null
        ? t('plugins.permissions.undeclared')
        : permissions.length
          ? t('plugins.permissions.needs', { list: permissions.map((item) => item.title).join(t('personas.separator')) })
          : t('plugins.permissions.none'),
    )
  if (isolation) parts.push(t(`plugins.candidate.isolation.${isolation}`))
  return parts.join(t('plugins.candidate.joiner'))
})

const tabNames = computed(() => {
  const names = ['settings', 'scenes', 'tools'] as string[]
  if (running.value?.skills.length) names.push('skills')
  names.push('logs', 'version')
  return names
})
const counts = computed<Record<string, number | undefined>>(() => ({
  scenes: scenesUsing(props.snapshot, props.name).length || undefined,
  tools: featureCount(running.value) + (running.value?.crons.length ?? 0) || undefined,
  skills: running.value?.skills.length || undefined,
  logs: (running.value?.errors.length ?? 0) + (running.value?.model_calls.filter((call) => call.error).length ?? 0) || undefined,
}))
const tabs = computed(() =>
  tabNames.value.map((value) => ({ value, label: t(`plugins.detail.tabs.${value}`), count: counts.value[value] })),
)
const tab = computed({
  get: () => (tabNames.value.includes(route.query.part as string) ? (route.query.part as string) : 'settings'),
  set: (value: string) => void router.replace({ query: { ...route.query, part: value } }),
})
const back = computed(() => ({ query: {} }))
const permissions = computed(() => permissionsOf(props.snapshot, props.name))
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <div>
      <Button variant="ghost" size="sm" :icon="ArrowLeft" :to="back" class="-ml-2">{{ t('plugins.all') }}</Button>
    </div>
    <header class="flex min-w-0 flex-wrap items-start gap-4">
      <span class="flex" :class="!enabled && 'opacity-60 grayscale'" aria-hidden="true">
        <Avatar :name="name" shape="square" :size="56" />
      </span>
      <div class="flex min-w-0 flex-1 flex-col gap-1.5">
        <div class="flex min-w-0 flex-wrap items-center gap-2">
          <h1 class="truncate text-2xl font-semibold">{{ name }}</h1>
          <Badge v-if="version" class="tabular">v{{ version }}</Badge>
          <Badge :tone="statusTone(status)" dot>{{ t(`plugins.status.${status}`) }}</Badge>
        </div>
        <p v-if="manifest?.description || running?.description" class="max-w-3xl text-sm text-muted">
          {{ running?.description || manifest?.description }}
        </p>
        <p v-if="manifest" class="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
          <span v-if="manifest.authors?.length">{{ manifest.authors.join(t('personas.separator')) }}</span>
          <span v-if="manifest.license">{{ manifest.license }}</span>
          <a v-if="manifest.repository" :href="manifest.repository" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-0.5 text-primary hover:underline">
            {{ t('plugins.detail.repository') }}<ArrowUpRight :size="13" aria-hidden="true" />
          </a>
          <a v-if="manifest.homepage" :href="manifest.homepage" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-0.5 text-primary hover:underline">
            {{ t('plugins.detail.homepage') }}<ArrowUpRight :size="13" aria-hidden="true" />
          </a>
        </p>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <Button v-if="enabled" :disabled="busy" :loading="working && !dirty" @click="disable">{{ t('plugins.detail.disable') }}</Button>
        <Button v-else-if="manifest" variant="primary" :disabled="busy" :loading="working" @click="save">
          {{ dirty ? t('plugins.detail.saveEnable') : t('plugins.detail.enable') }}
        </Button>
        <DropdownMenu v-if="menu.length" :items="menu">
          <IconButton :icon="MoreHorizontal" :label="t('common.more')" variant="secondary" :tooltip="false" />
        </DropdownMenu>
      </div>
    </header>

    <div v-if="source?.candidate" class="flex flex-wrap items-center gap-3 rounded-lg bg-info-bg px-4 py-3 text-sm text-info">
      <p class="min-w-0 flex-1">
        <strong class="font-semibold">{{ t('plugins.candidate.ready', { version: source.candidate.version }) }}</strong>
        · {{ source.application === 'host' ? (source.requested ? t('plugins.candidate.requested') : t('plugins.candidate.restart')) : t('plugins.candidate.reload') }}
        <template v-if="changeText"> · {{ changeText }}</template>
      </p>
      <div class="flex items-center gap-2">
        <Button size="sm" variant="ghost" :disabled="busy" @click="act('cancel')">{{ t('plugins.candidate.cancel') }}</Button>
        <Button size="sm" variant="primary" :disabled="busy || dirty" :loading="working" @click="act('apply')">
          {{ source.application === 'host' ? t('plugins.candidate.applyRestart') : t('plugins.candidate.apply') }}
        </Button>
      </div>
    </div>
    <p v-if="status === 'degraded'" class="rounded-md bg-warning-bg px-3 py-2 text-sm text-warning">
      {{
        health?.errors_last_hour
          ? t('plugins.detail.unstable', { n: health.errors_last_hour }, health.errors_last_hour)
          : t('plugins.detail.failing', { names: health?.failing.join(t('personas.separator')) ?? '' })
      }}
    </p>
    <ErrorNote v-if="source?.error" :title="t('plugins.detail.applyFailed')" :error="source.error" />
    <ErrorNote v-if="running?.error" :title="t('plugins.detail.startFailed')" :error="running.error" :retry="() => act('reload')" />
    <ErrorNote v-for="entry in entries.filter((item) => item.error)" :key="entry.directory" :title="t('plugins.detail.manifestFailed')" :error="entry.error" />
    <p v-if="entries.length > 1" class="rounded-md bg-warning-bg px-3 py-2 text-sm text-warning">{{ t('plugins.detail.duplicate') }}</p>
    <p v-if="permissions === null && (manifest || running)" class="rounded-md bg-warning-bg px-3 py-2 text-sm text-warning">
      {{ t('plugins.permissions.undeclared') }}
    </p>

    <Tabs v-model="tab" :items="tabs" :label="name" />
    <KeepAlive>
      <SettingsTab
        v-if="tab === 'settings'"
        v-model="draft"
        :fields="fields"
        :readable="Boolean(manifest)"
        :scene-choices="snapshot.scene_choices"
        :configured="configured"
        :problems="shownProblems"
      />
      <ScenesTab v-else-if="tab === 'scenes'" :name="name" :snapshot="snapshot" />
      <ToolsTab v-else-if="tab === 'tools'" :name="name" :snapshot="snapshot" />
      <SkillsTab v-else-if="tab === 'skills'" :running="running!" />
      <LogsTab v-else-if="tab === 'logs'" :name="name" :running="running" />
      <VersionTab v-else :name="name" :snapshot="snapshot" @update="update" @rollback="act('rollback')" />
    </KeepAlive>
    <SaveBar
      v-if="tab === 'settings'"
      :dirty="dirty"
      :saving="working"
      :error="saveError ?? (dirty && invalid ? Object.values(problems)[0] : null)"
      :invalid="invalid"
      :save-label="enabled ? undefined : t('plugins.detail.saveEnable')"
      @save="save"
      @discard="
        () => {
          draft = initial
          saveError = null
        }
      "
    />
  </div>
</template>
