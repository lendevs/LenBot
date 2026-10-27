<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'
import { TriangleAlert } from '@lucide/vue'
import { memoryApi, type MemoryScope } from '../../../api/memory'
import { keys } from '../../../api/query'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { confirm } from '../../../ui/confirm'
import BrowseView from './BrowseView.vue'
import IndexView from './IndexView.vue'
import IngestView from './IngestView.vue'
import MemorySettingsView from './MemorySettingsView.vue'
import PluginMemory from './PluginMemory.vue'
import SearchView from './SearchView.vue'

const props = defineProps<{ scene: string; timeZone: string }>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

type View = 'browse' | 'search' | 'ingest' | 'index' | 'settings'
const { t } = useI18n()
const route = useRoute()
const state = useQuery({ queryKey: keys.memory.state(), queryFn: ({ signal }) => memoryApi.state(signal) })
const enabled = computed(() => state.data.value?.enabled ?? false)
const entry = computed(() => (state.data.value?.scenes ?? []).find((item) => item.scene === props.scene))
const used = computed(() => entry.value !== undefined)
// A group whose memory is a plugin has no native upkeep.
const views = computed(() =>
  (enabled.value
    ? (['browse', 'search', 'ingest', 'index', 'settings'] as const).filter(
        (value) => value !== 'ingest' || !entry.value?.plugin,
      )
    : (['settings'] as const)
  ).map((value) => ({ value, label: t(`groups.memory.views.${value}`) })),
)
const initial = route.query.tab
const chosen = ref<View>(
  typeof initial === 'string' && ['browse', 'search', 'ingest', 'index', 'settings'].includes(initial)
    ? (initial as View)
    : 'browse',
)
const view = computed<View>(() =>
  !enabled.value ? 'settings' : chosen.value === 'ingest' && entry.value?.plugin ? 'browse' : chosen.value,
)

/** A file opened from search results. */
const opening = ref<{ scope: MemoryScope; path: string } | null>(null)
function openHit(hit: { scope: MemoryScope; path: string }) {
  opening.value = { scope: hit.scope, path: hit.path }
  chosen.value = 'browse'
}

const dirty = reactive<Record<string, boolean>>({})
watch(
  () => Object.values(dirty).some(Boolean),
  (value) => emit('dirty', value),
  { immediate: true },
)
const selected = computed({
  get: () => view.value,
  set: (value: View) => void switchTo(value),
})
async function switchTo(value: View) {
  const current = view.value
  if (dirty[current] && !(await confirm({ title: t('common.unsaved'), confirmLabel: t('common.discard') })))
    return
  dirty[current] = false
  chosen.value = value
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <Skeleton v-if="state.isPending.value" :lines="6" />
    <ErrorNote
      v-else-if="state.isError.value"
      :title="t('groups.memory.readFailed')"
      :error="state.error.value"
      :retry="state.refetch"
    />
    <template v-else-if="state.data.value">
      <PluginMemory
        v-if="entry?.plugin || entry?.recap_plugin"
        :plugin="entry.plugin"
        :recap="entry.recap_plugin"
        :time-zone="timeZone"
      />
      <p v-if="!enabled" class="rounded-lg border border-line px-4 py-3 text-sm text-muted">
        {{ t('groups.memory.off') }}
      </p>
      <div
        v-if="state.data.value.index?.needs_rebuild && view !== 'index'"
        class="flex flex-wrap items-center gap-3 rounded-lg bg-warning-bg px-4 py-3 text-sm text-warning"
      >
        <TriangleAlert :size="16" aria-hidden="true" />
        <span class="min-w-0 flex-1">{{ t('groups.memory.needsRebuild') }}</span>
        <Button size="sm" @click="selected = 'index'">{{ t('groups.memory.toIndex') }}</Button>
      </div>
      <SegmentedControl
        v-if="views.length > 1"
        v-model="selected"
        :options="views"
        :label="t('groups.tabs.memory')"
        class="self-start"
      />

      <MemorySettingsView v-if="view === 'settings'" @dirty="(value: boolean) => (dirty.settings = value)" />
      <IndexView
        v-else-if="view === 'index' && state.data.value.index"
        :index="state.data.value.index"
        :reindexing="state.data.value.reindexing"
      />
      <EmptyState v-else-if="!used" :title="t('groups.memory.unused')" />
      <BrowseView
        v-else-if="view === 'browse'"
        :scene="scene"
        :state="state.data.value"
        :time-zone="timeZone"
        :opening="opening"
        @opened="opening = null"
        @dirty="(value: boolean) => (dirty.browse = value)"
      />
      <SearchView v-else-if="view === 'search'" :scene="scene" @open="openHit" />
      <IngestView v-else-if="view === 'ingest'" :scene="scene" :time-zone="timeZone" />
    </template>
  </div>
</template>
