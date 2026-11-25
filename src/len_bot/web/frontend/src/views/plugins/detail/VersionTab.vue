<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RotateCcw, ShieldAlert, Upload } from '@lucide/vue'
import type { Permission, PluginsSnapshot, Source } from '../../../api/plugins'
import { developerDetails } from '../../../composables/useDeveloperMode'
import { groupLabel } from '../../../layouts/shell/scenes'
import Button from '../../../ui/Button.vue'
import RawRecord from '../../groups/tasks/RawRecord.vue'
import { usePluginsState } from '../state'
import { manifestOf, runningOf, sceneSecondaryId } from '../view'

const props = defineProps<{ name: string; snapshot: PluginsSnapshot }>()
const emit = defineEmits<{ update: []; rollback: [] }>()

const { t } = useI18n()
const state = usePluginsState()
const manifest = computed(() => manifestOf(props.snapshot, props.name))
const running = computed(() => runningOf(props.snapshot, props.name))
const source = computed(() => manifest.value?.source ?? null)
const entries = computed(() => props.snapshot.available[props.name] ?? [])
const installedManifest = computed(() => manifest.value?.installed_manifest ?? null)
const origin = (item: Source) =>
  [item.kind, item.location, item.ref || item.branch || item.revision.slice(0, 12)].join(' · ')

const permissionKey = (list: Permission[] | null | undefined) =>
  list == null
    ? null
    : list
        .map((item) => item.name)
        .sort()
        .join(',')
const platformKey = (list: string[] | null | undefined) => (list == null ? null : [...list].sort().join(','))
const formatPlatforms = (list: string[] | null | undefined) =>
  list?.length
    ? list.map((platform) => t(`plugins.chatPlatforms.${platform}`)).join(t('personas.separator'))
    : t('plugins.candidate.allPlatforms')

interface CandidateDiffItem {
  text: string
  warning: boolean
}

/**
 * Compare candidate manifest against the installed one.
 * Prefer `running` only when actively running; fall back to `entry.installed_manifest` so disabled or failed
 * plugins never lose permission, platform or data_version warnings.
 */
const candidateDiff = computed<CandidateDiffItem[]>(() => {
  const next = manifest.value
  if (!source.value?.candidate || !next) return []
  const live = running.value?.status === 'running' ? running.value : null
  const installed = installedManifest.value
  if (!live && !installed) return []

  const items: CandidateDiffItem[] = []
  const nowPermissions = live ? live.permissions : installed!.permissions
  if ('permissions' in next && permissionKey(nowPermissions) !== permissionKey(next.permissions)) {
    const nextPermissions = next.permissions ?? null
    if (nextPermissions === null) {
      items.push({ text: t('plugins.permissions.undeclared'), warning: true })
    } else if (nowPermissions !== null) {
      const existing = new Set(nowPermissions.map((item) => item.name))
      const added = nextPermissions.filter((item) => !existing.has(item.name))
      if (added.length) {
        items.push({
          text: t('plugins.version.permissionsAdded', {
            list: added.map((item) => item.title).join(t('personas.separator')),
          }),
          warning: true,
        })
      } else {
        items.push({
          text: t('plugins.version.permissionsChanged', {
            list: nextPermissions.length
              ? nextPermissions.map((item) => item.title).join(t('personas.separator'))
              : t('common.none'),
          }),
          warning: false,
        })
      }
    } else {
      items.push({
        text: t('plugins.version.permissionsChanged', {
          list: nextPermissions.length
            ? nextPermissions.map((item) => item.title).join(t('personas.separator'))
            : t('common.none'),
        }),
        warning: false,
      })
    }
  }

  const nowPlatforms = live ? live.chat_platforms : installed!.chat_platforms
  if ('chat_platforms' in next && platformKey(nowPlatforms) !== platformKey(next.chat_platforms)) {
    const narrowed =
      next.chat_platforms !== null &&
      next.chat_platforms !== undefined &&
      (nowPlatforms === null || nowPlatforms.some((item) => !next.chat_platforms!.includes(item)))
    items.push({
      text: t('plugins.version.chatPlatformsChanged', {
        from: formatPlatforms(nowPlatforms),
        to: formatPlatforms(next.chat_platforms),
      }),
      warning: narrowed,
    })
  }

  if (installed && next.data_version !== undefined && next.data_version !== installed.data_version) {
    items.push({
      text: t('plugins.version.dataVersionChanged', {
        from: installed.data_version,
        to: next.data_version,
      }),
      warning: next.data_version > installed.data_version,
    })
  }

  return items
})
const candidateHasWarning = computed(() => candidateDiff.value.some((item) => item.warning))

const runningScenes = computed(() => running.value?.scenes ?? [])
const dataVersionText = computed(() => {
  const next = manifest.value?.data_version
  const prev = installedManifest.value?.data_version
  if (prev !== undefined && next !== undefined && prev !== next) return `v${prev} → v${next}`
  if (next && next > 1) return `v${next}`
  return ''
})
const facts = computed(() => {
  const value = source.value
  const rows: [string, string][] = [
    [
      t('plugins.version.source'),
      value?.installed
        ? `v${value.installed.version}`
        : value
          ? t('plugins.version.notApplied')
          : manifest.value?.version
            ? `v${manifest.value.version}`
            : '',
    ],
    [t('plugins.version.candidate'), value?.candidate ? `v${value.candidate.version}` : ''],
    [
      t('plugins.version.running'),
      running.value?.version ? `v${running.value.version}` : t('plugins.version.notLoaded'),
    ],
    [t('plugins.version.groups'), runningScenes.value.length ? '_scenes' : t('plugins.version.noGroups')],
    [t('plugins.version.installedFrom'), value?.installed ? origin(value.installed) : ''],
    [t('plugins.version.candidateFrom'), value?.candidate ? origin(value.candidate) : ''],
    [
      t('plugins.version.previous'),
      value?.previous ? `v${value.previous.version} · ${origin(value.previous)}` : '',
    ],
    [
      t('plugins.version.compatible'),
      manifest.value?.requires_lenbot
        ? t('plugins.version.requires', {
            host: manifest.value.requires_lenbot,
            python: manifest.value.requires_python,
            platforms: (manifest.value.platforms ?? []).join(t('personas.separator')),
          })
        : '',
    ],
    [
      t('plugins.version.chatPlatforms'),
      (manifest.value?.chat_platforms ?? [])
        .map((platform) => t(`plugins.chatPlatforms.${platform}`))
        .join(t('personas.separator')),
    ],
    [t('plugins.version.dependencies'), (manifest.value?.dependencies ?? []).join(t('personas.separator'))],
    [t('plugins.version.dataVersion'), dataVersionText.value],
    [
      t('plugins.version.reload'),
      manifest.value?.reload ? t(`plugins.version.reloadBy.${manifest.value.reload}`) : '',
    ],
    [t('plugins.version.directory'), entries.value.map((entry) => entry.directory).join('\n')],
  ]
  return rows.filter(([, value]) => value)
})
</script>

<template>
  <div class="flex min-w-0 max-w-3xl flex-col gap-5">
    <section
      v-if="candidateDiff.length"
      class="flex items-start gap-3 rounded-lg px-4 py-3 text-sm"
      :class="candidateHasWarning ? 'bg-warning-bg text-warning' : 'bg-info-bg text-info'"
    >
      <ShieldAlert v-if="candidateHasWarning" :size="18" class="mt-0.5 shrink-0" aria-hidden="true" />
      <div class="flex min-w-0 flex-1 flex-col gap-1">
        <strong class="font-semibold">{{ t('plugins.version.candidateChanges') }}</strong>
        <ul class="flex list-none flex-col gap-0.5 tabular">
          <li v-for="(item, index) in candidateDiff" :key="index">{{ item.text }}</li>
        </ul>
      </div>
    </section>

    <section class="flex flex-col gap-4">
      <dl class="divide-y divide-line border-y border-line text-sm">
        <div
          v-for="[label, value] in facts"
          :key="label"
          class="grid gap-x-6 gap-y-1 py-2.5 sm:grid-cols-[9.5rem_minmax(0,1fr)]"
        >
          <dt class="text-muted">{{ label }}</dt>
          <dd
            v-if="value === '_scenes'"
            class="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1 text-ink-2"
          >
            <span v-for="scene in runningScenes" :key="scene" class="inline-flex items-baseline gap-1">
              <span class="font-medium text-ink">{{ groupLabel(scene) }}</span>
              <span v-if="sceneSecondaryId(scene)" class="font-mono text-xs text-muted tabular">
                {{ sceneSecondaryId(scene) }}
              </span>
            </span>
          </dd>
          <dd
            v-else
            class="min-w-0 break-words whitespace-pre-line text-ink-2 tabular"
            :class="label === t('plugins.version.directory') && 'font-mono text-xs'"
          >
            {{ value }}
          </dd>
        </div>
      </dl>
      <div
        v-if="source?.installed?.kind === 'git' || (source?.previous && !source.candidate)"
        class="flex flex-wrap gap-2"
      >
        <Button
          v-if="source?.installed?.kind === 'git'"
          size="sm"
          :icon="Upload"
          :disabled="state.busy.value !== null"
          @click="emit('update')"
        >
          {{ t('plugins.detail.update') }}
        </Button>
        <Button
          v-if="source?.previous && !source.candidate"
          size="sm"
          variant="ghost"
          :icon="RotateCcw"
          :disabled="state.busy.value !== null"
          @click="emit('rollback')"
        >
          {{ t('plugins.version.rollback', { version: source.previous.version }) }}
        </Button>
      </div>
    </section>
    <RawRecord
      v-if="developerDetails"
      :label="t('plugins.version.raw')"
      :code="{ available: entries, running }"
    />
  </div>
</template>
