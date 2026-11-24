<script setup lang="ts">
import { computed, provide, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  onBeforeRouteUpdate,
  useRoute,
  useRouter,
  type LocationQueryRaw,
  type RouteLocationRaw,
} from 'vue-router'
import { ArrowLeft, Blocks } from '@lucide/vue'
import type { PluginsSnapshot } from '../../api/plugins'
import Button from '../../ui/Button.vue'
import EmptyState from '../../ui/EmptyState.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Skeleton from '../../ui/Skeleton.vue'
import Tabs from '../../ui/Tabs.vue'
import { toast } from '../../ui/toast'
import DiscoverView from './DiscoverView.vue'
import InstallDialog, { type InstallRequest } from './InstallDialog.vue'
import InstalledList from './InstalledList.vue'
import PluginDetail from './detail/PluginDetail.vue'
import { pluginsKey, usePlugins } from './state'
import { manifestOf, pluginNames } from './view'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const state = usePlugins()
provide(pluginsKey, state)
const snapshot = computed(() => state.snapshot.data.value)

const queryText = (value: unknown) => (typeof value === 'string' ? value : '')

type View = 'installed' | 'discover'
const view = computed<View>({
  get: () => (route.query.view === 'discover' ? 'discover' : 'installed'),
  set: (value) => void router.replace({ query: value === 'discover' ? { view: value } : {} }),
})
const views = computed(() => [
  {
    value: 'installed' as const,
    label: t('plugins.views.installed'),
    count: snapshot.value ? pluginNames(snapshot.value).length || undefined : undefined,
  },
  { value: 'discover' as const, label: t('plugins.views.discover') },
])
const item = computed(() => queryText(route.query.item))
const known = computed(() => Boolean(snapshot.value && pluginNames(snapshot.value).includes(item.value)))

function discoverBackQuery(source: Record<string, unknown>): LocationQueryRaw {
  const query: LocationQueryRaw = { view: 'discover' }
  const q = queryText(source.q).trim()
  const cat = queryText(source.cat)
  if (q) query.q = q
  if (cat) query.cat = cat
  return query
}

const backTarget = computed<RouteLocationRaw>(() => ({
  query: route.query.from === 'discover' ? discoverBackQuery(route.query) : {},
}))

// Returning from a plugin detail opened via Discover restores the Discover view and filters.
onBeforeRouteUpdate((to, from) => {
  if (
    queryText(from.query.item) &&
    from.query.from === 'discover' &&
    !queryText(to.query.item) &&
    !queryText(to.query.view)
  ) {
    return { path: to.path, query: discoverBackQuery(from.query) }
  }
})

export interface OpenOptions {
  part?: string
  q?: string
  cat?: string | null
  replace?: boolean
}

function open(name: string, options?: OpenOptions) {
  const query: LocationQueryRaw = { item: name }
  if (options?.part) query.part = options.part
  const fromDiscover = view.value === 'discover' || route.query.from === 'discover'
  if (fromDiscover) {
    query.from = 'discover'
    const q = (options?.q !== undefined ? options.q : queryText(route.query.q)).trim()
    const cat = options?.cat !== undefined ? (options.cat ?? '') : queryText(route.query.cat)
    if (q) query.q = q
    if (cat) query.cat = cat
  }
  if (options?.replace) void router.replace({ query })
  else void router.push({ query })
}

const request = ref<InstallRequest | null>(null)
function afterAction(result: PluginsSnapshot) {
  const current = request.value
  const kind = current?.kind
  request.value = null
  const name = result.operation?.name ?? (current?.kind === 'update' ? current.name : undefined)
  toast.success(
    result.operation?.needs_config ? t('plugins.install.readyConfigure') : t('plugins.install.ready'),
  )
  if (!name) return
  if (kind === 'update') {
    if (manifestOf(result, name)?.source?.candidate) {
      open(name, { part: 'version', replace: item.value === name })
    }
    return
  }
  open(name)
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-6 pb-2">
    <Tabs v-if="!item" v-model="view" :items="views" :label="t('shell.pages.plugins')" />
    <Skeleton v-if="state.snapshot.isPending.value" :lines="6" />
    <ErrorNote
      v-else-if="state.snapshot.isError.value"
      :title="t('plugins.readFailed')"
      :error="state.snapshot.error.value"
      :retry="state.snapshot.refetch"
    />
    <template v-else-if="snapshot">
      <template v-if="item">
        <PluginDetail
          v-if="known"
          :key="item"
          :name="item"
          :snapshot="snapshot"
          @install="(value) => (request = value)"
        />
        <EmptyState v-else :icon="Blocks" :title="t('plugins.missing', { name: item })">
          <Button :icon="ArrowLeft" :to="backTarget">
            {{ route.query.from === 'discover' ? t('plugins.views.discover') : t('plugins.all') }}
          </Button>
        </EmptyState>
      </template>
      <Transition v-else name="ui-tab" mode="out-in">
        <DiscoverView
          v-if="view === 'discover'"
          key="discover"
          :snapshot="snapshot"
          @open="open"
          @install="(value) => (request = value)"
        />
        <InstalledList
          v-else
          key="installed"
          :snapshot="snapshot"
          @open="open"
          @install="(value) => (request = value)"
          @discover="view = 'discover'"
        />
      </Transition>
    </template>
    <InstallDialog v-if="request" :request="request" @done="afterAction" @close="request = null" />
  </div>
</template>
