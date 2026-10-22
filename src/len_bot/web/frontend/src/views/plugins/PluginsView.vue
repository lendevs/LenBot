<script setup lang="ts">
import { computed, provide, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
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
import { pluginNames } from './view'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const state = usePlugins()
provide(pluginsKey, state)
const snapshot = computed(() => state.snapshot.data.value)

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
const item = computed(() => (typeof route.query.item === 'string' ? route.query.item : ''))
const known = computed(() => Boolean(snapshot.value && pluginNames(snapshot.value).includes(item.value)))
const open = (name: string) => void router.push({ query: { item: name } })

const request = ref<InstallRequest | null>(null)
function installed(result: PluginsSnapshot) {
  const kind = request.value?.kind
  request.value = null
  const name = result.operation?.name
  toast.success(
    result.operation?.needs_config ? t('plugins.install.readyConfigure') : t('plugins.install.ready'),
  )
  if (name && kind !== 'update') open(name)
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
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
          <Button :icon="ArrowLeft" :to="{ query: {} }">{{ t('plugins.all') }}</Button>
        </EmptyState>
      </template>
      <DiscoverView
        v-else-if="view === 'discover'"
        :snapshot="snapshot"
        @open="open"
        @install="(value) => (request = value)"
      />
      <InstalledList
        v-else
        :snapshot="snapshot"
        @open="open"
        @install="(value) => (request = value)"
        @discover="view = 'discover'"
      />
    </template>
    <InstallDialog v-if="request" :request="request" @done="installed" @close="request = null" />
  </div>
</template>
