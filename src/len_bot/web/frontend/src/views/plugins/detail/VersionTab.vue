<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RotateCcw, Upload } from '@lucide/vue'
import type { PluginsSnapshot, Source } from '../../../api/plugins'
import { developerDetails } from '../../../composables/useDeveloperMode.js'
import { groupLabel } from '../../../layouts/shell/scenes'
import Button from '../../../ui/Button.vue'
import RawRecord from '../../groups/tasks/RawRecord.vue'
import { usePluginsState } from '../state'
import { manifestOf, runningOf } from '../view'

const props = defineProps<{ name: string; snapshot: PluginsSnapshot }>()
const emit = defineEmits<{ update: []; rollback: [] }>()

const { t } = useI18n()
const state = usePluginsState()
const manifest = computed(() => manifestOf(props.snapshot, props.name))
const running = computed(() => runningOf(props.snapshot, props.name))
const source = computed(() => manifest.value?.source ?? null)
const entries = computed(() => props.snapshot.available[props.name] ?? [])
const origin = (item: Source) => [item.kind, item.location, item.ref || item.branch || item.revision.slice(0, 12)].join(' · ')

const facts = computed(() => {
  const value = source.value
  const rows: [string, string][] = [
    [t('plugins.version.source'), value?.installed ? `v${value.installed.version}` : value ? t('plugins.version.notApplied') : manifest.value?.version ? `v${manifest.value.version}` : ''],
    [t('plugins.version.candidate'), value?.candidate ? `v${value.candidate.version}` : ''],
    [t('plugins.version.running'), running.value?.version ? `v${running.value.version}` : t('plugins.version.notLoaded')],
    [t('plugins.version.groups'), running.value?.scenes.map(groupLabel).join(t('personas.separator')) || t('plugins.version.noGroups')],
    [t('plugins.version.installedFrom'), value?.installed ? origin(value.installed) : ''],
    [t('plugins.version.candidateFrom'), value?.candidate ? origin(value.candidate) : ''],
    [t('plugins.version.previous'), value?.previous ? `v${value.previous.version} · ${origin(value.previous)}` : ''],
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
    [t('plugins.version.dependencies'), (manifest.value?.dependencies ?? []).join(t('personas.separator'))],
    [t('plugins.version.reload'), manifest.value?.reload ? t(`plugins.version.reloadBy.${manifest.value.reload}`) : ''],
    [t('plugins.version.directory'), entries.value.map((entry) => entry.directory).join('\n')],
  ]
  return rows.filter(([, value]) => value)
})
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
    <section class="flex flex-col gap-4 rounded-xl border border-line bg-surface p-5">
      <dl class="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-[max-content_minmax(0,1fr)]">
        <template v-for="[label, value] in facts" :key="label">
          <dt class="text-muted">{{ label }}</dt>
          <dd class="min-w-0 break-words whitespace-pre-line text-ink-2" :class="label === t('plugins.version.directory') && 'font-mono text-xs'">{{ value }}</dd>
        </template>
      </dl>
      <div v-if="source?.installed?.kind === 'git' || (source?.previous && !source.candidate)" class="flex flex-wrap gap-2 border-t border-line pt-4">
        <Button v-if="source?.installed?.kind === 'git'" size="sm" :icon="Upload" :disabled="state.busy.value !== null" @click="emit('update')">
          {{ t('plugins.detail.update') }}
        </Button>
        <Button v-if="source?.previous && !source.candidate" size="sm" variant="ghost" :icon="RotateCcw" :disabled="state.busy.value !== null" @click="emit('rollback')">
          {{ t('plugins.version.rollback', { version: source.previous.version }) }}
        </Button>
      </div>
    </section>
    <RawRecord v-if="developerDetails" :label="t('plugins.version.raw')" :code="{ available: entries, running }" />
  </div>
</template>
