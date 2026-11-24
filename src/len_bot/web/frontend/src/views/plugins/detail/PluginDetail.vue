<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ArrowUpRight, MoreHorizontal, RefreshCw, RotateCcw, Trash2, Upload } from '@lucide/vue'
import {
  pluginsApi,
  pluginTitle,
  type Permission,
  type PluginAction,
  type PluginsSnapshot,
} from '../../../api/plugins'
import { useUnsavedChanges } from '../../../composables/useUnsavedChanges'
import Avatar from '../../../ui/Avatar.vue'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import DropdownMenu, { type MenuEntry } from '../../../ui/DropdownMenu.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import IconButton from '../../../ui/IconButton.vue'
import SaveBar from '../../../ui/SaveBar.vue'
import Tabs, { type TabItem } from '../../../ui/Tabs.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import type { InstallRequest } from '../InstallDialog.vue'
import { configBody, formProblems, initialDraft, type Draft } from '../schema/config'
import { usePluginsState } from '../state'
import {
  chatPlatformsOf,
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
const detailRoot = ref<HTMLElement>()

const title = computed(() => pluginTitle(props.snapshot, props.name))
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
const catalogUpdate = computed(() => props.snapshot.updates?.find((item) => item.name === props.name) ?? null)
const isFirstInstallCandidate = computed(() => Boolean(source.value?.candidate && !source.value?.installed))

// The draft of the settings tab lives here, so the header action and SaveBar stay in sync across tabs.
const fields = computed(() => manifest.value?.fields ?? [])
const saved = computed(() => props.snapshot.saved.plugins[props.name])
const initial = computed(() => initialDraft(fields.value, saved.value))
const baseInitial = ref<Draft>(initial.value)
const draft = ref<Draft>(initial.value)
const remoteUpdated = ref(false)
const jsonError = ref<string | null>(null)
const draftRevision = ref(0)
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const dirty = computed(() => !same(draft.value, baseInitial.value) || jsonError.value !== null)

watch(initial, (next) => {
  if (same(next, baseInitial.value)) {
    remoteUpdated.value = false
    return
  }
  if (!dirty.value) {
    baseInitial.value = next
    draft.value = next
    remoteUpdated.value = false
    draftRevision.value += 1
    return
  }
  remoteUpdated.value = true
})

const configured = computed(() =>
  Object.fromEntries(
    Object.entries(saved.value ?? {}).map(([key, item]) => [key, 'configured' in item && item.configured]),
  ),
)
const problems = computed(() => formProblems(fields.value, draft.value, configured.value, t))
const problemList = computed(() =>
  jsonError.value ? [jsonError.value, ...Object.values(problems.value)] : Object.values(problems.value),
)
const invalid = computed(() => problemList.value.length > 0)
// An untouched form does not start out red; errors show once it changes or saving/enabling is tried.
const triedSave = ref(false)
const shownProblems = computed(() => (dirty.value || triedSave.value ? problems.value : {}))
useUnsavedChanges(dirty, { keep: ['part', 'from', 'q', 'cat'] })

const saveError = ref<string | null>(null)
const rawSaveError = ref<string | null>(null)
watch(
  [draft, jsonError],
  () => {
    saveError.value = null
    rawSaveError.value = null
  },
  { deep: true },
)

function reloadRemote() {
  baseInitial.value = initial.value
  draft.value = initial.value
  remoteUpdated.value = false
  jsonError.value = null
  saveError.value = null
  rawSaveError.value = null
  triedSave.value = false
  draftRevision.value += 1
}

function adoptSavedSnapshot(result: PluginsSnapshot) {
  const nextFields = manifestOf(result, props.name)?.fields ?? []
  const next = initialDraft(nextFields, result.saved.plugins[props.name])
  baseInitial.value = next
  draft.value = next
  remoteUpdated.value = false
  jsonError.value = null
  saveError.value = null
  rawSaveError.value = null
  triedSave.value = false
  draftRevision.value += 1
}

async function focusFirstInvalid() {
  triedSave.value = true
  if (tab.value !== 'settings') {
    tab.value = 'settings'
    await nextTick()
    await nextTick()
  } else {
    await nextTick()
  }
  const root = detailRoot.value
  if (!root) return
  let target = root.querySelector<HTMLElement>('[data-invalid], [aria-invalid="true"]')
  if (!target) {
    const collapsedErrorRow = root.querySelector<HTMLElement>('[data-row-error]')
    if (collapsedErrorRow) {
      collapsedErrorRow.click()
      await nextTick()
      target = root.querySelector<HTMLElement>('[data-invalid], [aria-invalid="true"]')
    }
  }
  if (!target) return
  target.scrollIntoView({ behavior: 'smooth', block: 'center' })
  const focusable = target.matches('input, textarea, select, button, [tabindex]')
    ? target
    : target.querySelector<HTMLElement>('input, textarea, select, button, [tabindex]')
  ;(focusable ?? target).focus({ preventScroll: true })
}

async function save(options: { applyCandidate?: boolean } = {}) {
  saveError.value = null
  rawSaveError.value = null
  const shouldApply = options.applyCandidate ?? isFirstInstallCandidate.value
  if (invalid.value) {
    triedSave.value = true
    void focusFirstInvalid()
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
    const result = await state.run(
      props.name,
      () => pluginsApi.save(props.name, true, config, shouldApply ? { applyCandidate: true } : undefined),
      { quiet: true },
    )
    if (result) {
      adoptSavedSnapshot(result)
      if (shouldApply) {
        const failed = result.running.plugins.some(
          (item) => item.name === props.name && item.status === 'failed',
        )
        if (failed) toast.error(t('plugins.detail.actionFailed'))
        else if (result.operation?.restart_required) toast.success(t('plugins.candidate.requested'))
        else toast.success(t('plugins.detail.done.apply'))
      } else {
        toast.success(wasOn ? t('common.saved') : t('plugins.detail.enabled'))
      }
    }
  } catch (error) {
    const described = describeError(error, t('ui.error.network'))
    saveError.value = described.message
    rawSaveError.value =
      described.raw && described.raw !== described.message
        ? described.status === null
          ? described.raw
          : `HTTP ${described.status}\n${described.raw}`
        : null
  }
}

async function applyCandidate() {
  if (dirty.value || isFirstInstallCandidate.value) {
    await save({ applyCandidate: true })
    return
  }
  if (invalid.value) {
    triedSave.value = true
    void focusFirstInvalid()
    return
  }
  await act('apply')
}

const disable = () =>
  state.run(props.name, () => pluginsApi.save(props.name, false), { success: t('plugins.detail.disabled') })

async function act(action: PluginAction) {
  const result = await state.run(props.name, () => pluginsApi.act(props.name, action))
  if (!result) return
  if (
    action === 'cancel' &&
    !(props.name in result.available) &&
    !(props.name in result.saved.plugins) &&
    !result.running.plugins.some((item) => item.name === props.name)
  ) {
    baseInitial.value = draft.value
    jsonError.value = null
    toast.success(t('plugins.detail.done.cancel'))
    void router.push(back.value)
    return
  }
  const failed = result.running.plugins.some((item) => item.name === props.name && item.status === 'failed')
  if (failed) toast.error(t('plugins.detail.actionFailed'))
  else if (action === 'apply' && result.operation?.restart_required)
    toast.success(t('plugins.candidate.requested'))
  else toast.success(t(`plugins.detail.done.${action}`))
}

async function confirmRollback() {
  const previous = source.value?.previous
  if (!previous) return
  const dataVersion = manifest.value?.installed_manifest?.data_version ?? manifest.value?.data_version ?? 1
  const hasData =
    loaded.value ||
    Boolean(running.value) ||
    props.snapshot.retained_data.some((item) => item.name === props.name)
  const message =
    dataVersion > 1
      ? t('plugins.version.rollbackDataVersionWarning', { dataVersion })
      : hasData
        ? t('plugins.version.rollbackDataWarning')
        : t('plugins.version.rollbackMessage')
  const sure = await confirm({
    title: t('plugins.version.rollbackTitle', { version: previous.version }),
    message,
    confirmLabel: t('plugins.version.rollbackConfirm'),
    tone: 'danger',
  })
  if (sure) await act('rollback')
}

async function uninstall() {
  const sure = await confirm({
    title: t('plugins.uninstall.title', { name: props.name }),
    message: t('plugins.uninstall.message'),
    confirmLabel: t('plugins.uninstall.confirm'),
    tone: 'danger',
  })
  if (!sure) return
  const result = await state.run(props.name, () => pluginsApi.uninstall(props.name), {
    success: t('plugins.uninstall.done'),
  })
  if (result) {
    baseInitial.value = draft.value
    jsonError.value = null
    void router.push(back.value)
  }
}
async function removeData() {
  const sure = await confirm({
    title: t('plugins.removeData.title', { name: props.name }),
    message: t('plugins.removeData.message'),
    confirmLabel: t('plugins.removeData.confirm'),
    tone: 'danger',
  })
  if (sure)
    await state.run(props.name, () => pluginsApi.removeData(props.name), {
      success: t('plugins.removeData.done'),
    })
}
const update = () => emit('install', { kind: 'update', name: props.name, ref: source.value?.ref ?? null })

const menu = computed<MenuEntry[]>(() => {
  const items: MenuEntry[] = []
  if (loaded.value && !isFirstInstallCandidate.value)
    items.push({
      label: t('plugins.detail.reload'),
      icon: RefreshCw,
      disabled: busy.value || dirty.value,
      select: () => void act('reload'),
    })
  if (source.value?.installed?.kind === 'git')
    items.push({
      label: t('plugins.detail.update'),
      icon: Upload,
      disabled: busy.value || dirty.value,
      select: update,
    })
  if (source.value?.previous && !source.value.candidate)
    items.push({
      label: t('plugins.version.rollback', { version: source.value.previous.version }),
      icon: RotateCcw,
      disabled: busy.value,
      select: () => void confirmRollback(),
    })
  if (manifest.value?.managed || disabledIn(props.snapshot, props.name)) items.push({ type: 'separator' })
  if (manifest.value?.managed)
    items.push({
      label: t('plugins.uninstall.confirm'),
      icon: Trash2,
      danger: true,
      disabled: busy.value,
      select: () => void uninstall(),
    })
  if (disabledIn(props.snapshot, props.name))
    items.push({
      label: t('plugins.removeData.confirm'),
      icon: Trash2,
      danger: true,
      disabled: busy.value,
      select: () => void removeData(),
    })
  return items
})

const permissionKey = (list: Permission[] | null | undefined) =>
  list == null
    ? null
    : list
        .map((item) => item.name)
        .sort()
        .join(',')
const platformKey = (list: string[] | null | undefined) => (list == null ? null : [...list].sort().join(','))

const changeText = computed(() => {
  const next = manifest.value
  if (!source.value?.candidate || !next) return ''
  const live = running.value?.status === 'running' ? running.value : null
  const installed = next.installed_manifest ?? null
  if (!live && !installed) return ''
  const parts: string[] = []
  const nowPermissions = live ? live.permissions : installed!.permissions
  if ('permissions' in next && permissionKey(nowPermissions) !== permissionKey(next.permissions)) {
    const nextPermissions = next.permissions ?? null
    parts.push(
      nextPermissions === null
        ? t('plugins.permissions.undeclared')
        : nextPermissions.length
          ? t('plugins.permissions.needs', {
              list: nextPermissions.map((item) => item.title).join(t('personas.separator')),
            })
          : t('plugins.permissions.none'),
    )
  }
  const nowPlatforms = live ? live.chat_platforms : installed!.chat_platforms
  if ('chat_platforms' in next && platformKey(nowPlatforms) !== platformKey(next.chat_platforms)) {
    const list = next.chat_platforms?.length
      ? next.chat_platforms
          .map((platform) => t(`plugins.chatPlatforms.${platform}`))
          .join(t('personas.separator'))
      : t('plugins.candidate.allPlatforms')
    parts.push(t('plugins.candidate.chatPlatforms', { list }))
  }
  if (installed && next.data_version !== undefined && next.data_version !== installed.data_version) {
    parts.push(t('plugins.candidate.dataVersion', { from: installed.data_version, to: next.data_version }))
  }
  if (live && next.isolation && (live.isolation || 'inline') !== (next.isolation || 'inline')) {
    parts.push(t(`plugins.candidate.isolation.${next.isolation}`))
  }
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
  tools:
    featureCount(running.value) +
      (running.value?.memory_entries.length ?? 0) +
      (running.value?.crons.length ?? 0) || undefined,
  skills: running.value?.skills.length || undefined,
  logs:
    (running.value?.errors.length ?? 0) +
      (running.value?.model_calls.filter((call) => call.error).length ?? 0) || undefined,
}))
const settingsDot = computed<'error' | 'warning' | false>(() =>
  problemList.value.length && (triedSave.value || dirty.value) ? 'error' : dirty.value ? 'warning' : false,
)
const tabs = computed<TabItem<string>[]>(() =>
  tabNames.value.map((value) => ({
    value,
    label: t(`plugins.detail.tabs.${value}`),
    count: counts.value[value],
    dot: value === 'settings' ? settingsDot.value : undefined,
  })),
)
const tab = computed({
  get: () =>
    tabNames.value.includes(route.query.part as string) ? (route.query.part as string) : 'settings',
  set: (value: string) => void router.replace({ query: { ...route.query, part: value } }),
})
const back = computed(() => {
  if (route.query.from === 'discover') {
    const query: Record<string, string> = { view: 'discover' }
    if (typeof route.query.q === 'string' && route.query.q) query.q = route.query.q
    if (typeof route.query.cat === 'string' && route.query.cat) query.cat = route.query.cat
    return { query }
  }
  return { query: {} }
})
const permissions = computed(() => permissionsOf(props.snapshot, props.name))
const enabledScenes = computed(() => scenesUsing(props.snapshot, props.name))
const compatibleSceneChoices = computed(() => {
  const platforms = chatPlatformsOf(props.snapshot, props.name)
  return props.snapshot.scene_choices.filter((scene) => !platforms || platforms.includes(scene.split(':')[0]))
})
const enablingPicked = ref(false)
const canEnablePicked = computed(() => enabled.value && !isFirstInstallCandidate.value)
async function enablePickedScenes(scenes: string[]) {
  const platforms = chatPlatformsOf(props.snapshot, props.name)
  const valid = scenes.filter(
    (scene) =>
      scene in props.snapshot.scenes &&
      props.snapshot.scenes[scene].saved !== null &&
      (!platforms || platforms.includes(scene.split(':')[0])),
  )
  if (!valid.length) return
  const next = [...new Set([...enabledScenes.value, ...valid])]
  enablingPicked.value = true
  try {
    await state.run(`scenes:${props.name}`, () => pluginsApi.putPluginScenes(props.name, next), {
      success: t('common.saved'),
    })
  } finally {
    enablingPicked.value = false
  }
}

const hasValidationError = computed(
  () => !saveError.value && (dirty.value || triedSave.value) && invalid.value,
)
const barError = computed(() => saveError.value ?? (hasValidationError.value ? problemList.value[0] : null))
const saveBarLabel = computed(() =>
  isFirstInstallCandidate.value
    ? t('plugins.detail.saveAndApply')
    : enabled.value
      ? undefined
      : t('plugins.detail.saveEnable'),
)
</script>

<template>
  <div ref="detailRoot" class="flex min-w-0 flex-col gap-5 pb-2">
    <div class="-ml-2 flex">
      <Button variant="ghost" size="sm" :icon="ArrowLeft" :to="back">
        {{ t('plugins.all') }}
      </Button>
    </div>
    <header class="flex min-w-0 flex-col gap-4 sm:flex-row sm:items-start">
      <div class="flex min-w-0 flex-1 items-start gap-4">
        <span class="flex shrink-0" :class="!enabled && 'opacity-60 grayscale'" aria-hidden="true">
          <Avatar :name="name" shape="square" :size="52" />
        </span>
        <div class="flex min-w-0 flex-1 flex-col gap-1.5">
          <div class="flex min-w-0 flex-wrap items-center gap-2">
            <h1 class="truncate text-2xl font-semibold text-ink">{{ title }}</h1>
            <Badge v-if="title !== name">
              <span class="font-mono">{{ name }}</span>
            </Badge>
            <span v-if="version" class="inline-flex tabular">
              <Badge>v{{ version }}</Badge>
            </span>
            <span v-if="catalogUpdate" class="inline-flex tabular">
              <Badge :tone="catalogUpdate.prepared ? 'info' : 'warning'">
                {{
                  catalogUpdate.prepared
                    ? t('plugins.updates.prepared')
                    : t('plugins.card.update', { version: catalogUpdate.version })
                }}
              </Badge>
            </span>
            <Badge :tone="statusTone(status)" dot>{{ t(`plugins.status.${status}`) }}</Badge>
          </div>
          <p v-if="manifest?.description || running?.description" class="max-w-3xl text-sm text-muted">
            {{ running?.description || manifest?.description }}
          </p>
          <p v-if="manifest" class="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
            <span v-if="manifest.authors?.length">{{ manifest.authors.join(t('personas.separator')) }}</span>
            <span v-if="manifest.license">{{ manifest.license }}</span>
            <a
              v-if="manifest.repository"
              :href="manifest.repository"
              target="_blank"
              rel="noopener noreferrer"
              class="inline-flex items-center gap-0.5 text-primary hover:underline"
            >
              {{ t('plugins.detail.repository') }}
              <ArrowUpRight :size="13" aria-hidden="true" />
            </a>
            <a
              v-if="manifest.homepage"
              :href="manifest.homepage"
              target="_blank"
              rel="noopener noreferrer"
              class="inline-flex items-center gap-0.5 text-primary hover:underline"
            >
              {{ t('plugins.detail.homepage') }}
              <ArrowUpRight :size="13" aria-hidden="true" />
            </a>
          </p>
        </div>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <Button
          v-if="isFirstInstallCandidate && manifest"
          variant="primary"
          :disabled="busy"
          :loading="working"
          @click="save({ applyCandidate: true })"
        >
          {{ t('plugins.detail.saveAndApply') }}
        </Button>
        <Button v-else-if="enabled" :disabled="busy" :loading="working && !dirty" @click="disable">
          {{ t('plugins.detail.disable') }}
        </Button>
        <Button v-else-if="manifest" variant="primary" :disabled="busy" :loading="working" @click="save()">
          {{ dirty ? t('plugins.detail.saveEnable') : t('plugins.detail.enable') }}
        </Button>
        <DropdownMenu v-if="menu.length" :items="menu">
          <IconButton :icon="MoreHorizontal" :label="t('common.more')" variant="secondary" :tooltip="false" />
        </DropdownMenu>
      </div>
    </header>

    <div
      v-if="source?.candidate"
      class="flex flex-wrap items-center gap-3 rounded-lg bg-info-bg px-4 py-3 text-sm text-info"
    >
      <p class="min-w-0 flex-1">
        <strong class="font-semibold">
          {{ t('plugins.candidate.ready', { version: source.candidate.version }) }}
        </strong>
        ·
        {{
          source.application === 'host'
            ? source.requested
              ? t('plugins.candidate.requested')
              : t('plugins.candidate.restart')
            : t('plugins.candidate.reload')
        }}
        <template v-if="changeText">· {{ changeText }}</template>
      </p>
      <div class="flex items-center gap-2">
        <Button size="sm" variant="ghost" :disabled="busy" @click="act('cancel')">
          {{ t('plugins.candidate.cancel') }}
        </Button>
        <Button size="sm" variant="primary" :disabled="busy" :loading="working" @click="applyCandidate">
          {{
            source.application === 'host'
              ? t('plugins.candidate.applyRestart')
              : dirty || isFirstInstallCandidate
                ? t('plugins.detail.saveAndApply')
                : t('plugins.candidate.apply')
          }}
        </Button>
      </div>
    </div>
    <div
      v-if="remoteUpdated"
      role="status"
      class="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-warning-bg px-3.5 py-2.5 text-sm text-warning"
    >
      <span class="min-w-0 flex-1">{{ t('ui.draft.remoteUpdated') }}</span>
      <Button size="sm" variant="ghost" @click="reloadRemote">
        {{ t('ui.draft.reloadRemote') }}
      </Button>
    </div>
    <p v-if="status === 'degraded'" class="rounded-md bg-warning-bg px-3 py-2 text-sm text-warning">
      {{
        health?.errors_last_hour
          ? t('plugins.detail.unstable', { n: health.errors_last_hour }, health.errors_last_hour)
          : t('plugins.detail.failing', { names: health?.failing.join(t('personas.separator')) ?? '' })
      }}
    </p>
    <ErrorNote v-if="source?.error" :title="t('plugins.detail.applyFailed')" :error="source.error" />
    <ErrorNote
      v-if="running?.error"
      :title="t('plugins.detail.startFailed')"
      :error="running.error"
      :retry="() => act('reload')"
    />
    <ErrorNote
      v-for="entry in entries.filter((item) => item.error)"
      :key="entry.directory"
      :title="t('plugins.detail.manifestFailed')"
      :error="entry.error"
    />
    <p v-if="entries.length > 1" class="rounded-md bg-warning-bg px-3 py-2 text-sm text-warning">
      {{ t('plugins.detail.duplicate') }}
    </p>
    <p
      v-if="permissions === null && (manifest || running)"
      class="rounded-md bg-warning-bg px-3 py-2 text-sm text-warning"
    >
      {{ t('plugins.permissions.undeclared') }}
    </p>

    <Tabs v-model="tab" :items="tabs" :label="title" />
    <KeepAlive>
      <SettingsTab
        v-if="tab === 'settings'"
        v-model="draft"
        :fields="fields"
        :readable="Boolean(manifest)"
        :scene-choices="compatibleSceneChoices"
        :enabled-scenes="enabledScenes"
        :configured="configured"
        :problems="shownProblems"
        :reset-key="draftRevision"
        :on-enable-picked="canEnablePicked ? enablePickedScenes : undefined"
        :enabling-picked="enablingPicked"
        @update:json-error="(value) => (jsonError = value)"
      />
      <ScenesTab v-else-if="tab === 'scenes'" :name="name" :snapshot="snapshot" />
      <ToolsTab v-else-if="tab === 'tools'" :name="name" :snapshot="snapshot" />
      <SkillsTab v-else-if="tab === 'skills'" :running="running!" />
      <LogsTab v-else-if="tab === 'logs'" :name="name" :running="running" />
      <VersionTab v-else :name="name" :snapshot="snapshot" @update="update" @rollback="confirmRollback" />
    </KeepAlive>
    <SaveBar
      :dirty="dirty"
      :saving="working"
      :error="barError"
      :raw-error="saveError ? rawSaveError : null"
      :invalid="invalid"
      :save-label="saveBarLabel"
      :action-label="hasValidationError ? t('common.locateError') : undefined"
      @save="save()"
      @discard="reloadRemote"
      @action="focusFirstInvalid"
    />
  </div>
</template>
