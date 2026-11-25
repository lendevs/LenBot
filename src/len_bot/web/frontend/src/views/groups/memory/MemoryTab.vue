<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
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

const VALID_VIEWS = ['browse', 'search', 'ingest', 'index', 'settings'] as const
type View = (typeof VALID_VIEWS)[number]
const isView = (value: unknown): value is View =>
  typeof value === 'string' && (VALID_VIEWS as readonly string[]).includes(value)

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const state = useQuery({
  queryKey: keys.memory.state(),
  queryFn: ({ signal }) => memoryApi.state(signal),
  refetchInterval: (query) => (query.state.data?.reindexing ? 3000 : false),
})
const enabled = computed(() => state.data.value?.enabled ?? false)
const entry = computed(() => (state.data.value?.scenes ?? []).find((item) => item.scene === props.scene))
const used = computed(() => entry.value !== undefined)
// A group whose memory is a plugin has no native upkeep.
const views = computed(() =>
  (enabled.value
    ? VALID_VIEWS.filter((value) => value !== 'ingest' || !entry.value?.plugin)
    : (['settings'] as const)
  ).map((value) => ({ value, label: t(`groups.memory.views.${value}`) })),
)
const chosen = ref<View>(isView(route.query.tab) ? route.query.tab : 'browse')
const view = computed<View>(() =>
  !enabled.value ? 'settings' : chosen.value === 'ingest' && entry.value?.plugin ? 'browse' : chosen.value,
)

function syncTabQuery(value: View) {
  const next = { ...route.query }
  if (value === 'browse') delete next.tab
  else next.tab = value
  if ((next.tab ?? undefined) === (route.query.tab ?? undefined)) return
  void router.replace({ query: next })
}

/** A file opened from search results. */
const browseScope = ref<MemoryScope>('scene')
const scopes = computed(() =>
  (['scene', 'public'] as const).map((value) => ({ value, label: t(`groups.memory.scopes.${value}`) })),
)
const opening = ref<{ scope: MemoryScope; path: string } | null>(null)
function openHit(hit: { scope: MemoryScope; path: string }) {
  browseScope.value = hit.scope
  opening.value = { scope: hit.scope, path: hit.path }
  chosen.value = 'browse'
  syncTabQuery('browse')
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
async function switchTo(value: View, updateRoute = true) {
  const current = view.value
  if (value === current) {
    if (updateRoute) syncTabQuery(value)
    return
  }
  if (dirty[current] && !(await confirm({ title: t('common.unsaved'), confirmLabel: t('common.discard') }))) {
    if (!updateRoute) syncTabQuery(current)
    return
  }
  dirty[current] = false
  chosen.value = value
  if (updateRoute) syncTabQuery(value)
}
watch(
  () => route.query.tab,
  (value) => {
    const next: View = isView(value) ? value : 'browse'
    if (next !== chosen.value) void switchTo(next, false)
  },
)
async function switchScope(value: MemoryScope) {
  if (value === browseScope.value) return
  if (dirty.browse && !(await confirm({ title: t('common.unsaved'), confirmLabel: t('common.discard') })))
    return
  dirty.browse = false
  browseScope.value = value
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
      <p v-if="!enabled" class="rounded-lg bg-fill px-4 py-3 text-sm text-muted">
        {{ t('groups.memory.off') }}
      </p>
      <div
        v-if="state.data.value.index?.needs_rebuild && view !== 'index'"
        class="flex flex-wrap items-center gap-3 rounded-lg bg-warning-bg px-4 py-3 text-sm text-warning"
      >
        <TriangleAlert :size="16" class="shrink-0" aria-hidden="true" />
        <span class="min-w-0 flex-1">{{ t('groups.memory.needsRebuild') }}</span>
        <Button size="sm" @click="selected = 'index'">{{ t('groups.memory.toIndex') }}</Button>
      </div>
      <div v-if="views.length > 1" class="flex flex-wrap items-center gap-2.5">
        <SegmentedControl v-model="selected" :options="views" :label="t('groups.tabs.memory')" />
        <template v-if="view === 'browse' && used && state.data.value.public_readable">
          <span class="h-4 w-px bg-line max-sm:hidden" aria-hidden="true" />
          <SegmentedControl
            :model-value="browseScope"
            :options="scopes"
            size="sm"
            :label="t('groups.memory.scope')"
            @update:model-value="switchScope"
          />
        </template>
      </div>

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
        :scope="browseScope"
        :state="state.data.value"
        :time-zone="timeZone"
        :opening="opening"
        @opened="opening = null"
        @dirty="(value: boolean) => (dirty.browse = value)"
      />
      <IngestView v-else-if="view === 'ingest'" :scene="scene" :time-zone="timeZone" />
      <KeepAlive>
        <SearchView
          v-if="used && view === 'search'"
          :scene="scene"
          :retrieval="state.data.value.index?.retrieval ?? null"
          @open="openHit"
        />
      </KeepAlive>
    </template>
  </div>
</template>
