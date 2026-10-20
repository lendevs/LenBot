<script setup lang="ts">
import { computed, onBeforeUnmount, provide, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useMediaQuery } from '@vueuse/core'
import { ChevronsUpDown, Plus } from '@lucide/vue'
import type { HostScene } from '../../api/host'
import { useCurrentScene } from '../../composables/useCurrentScene.js'
import { useUnsavedChanges } from '../../composables/useUnsavedChanges.js'
import { useHostEvents } from '../../host/events.js'
import { host, readHostState } from '../../host/store.js'
import TasksPage from '../../host/pages/tasks/TasksPage.vue'
import { groupLabel } from '../../layouts/shell/scenes'
import Avatar from '../../ui/Avatar.vue'
import Button from '../../ui/Button.vue'
import EmptyState from '../../ui/EmptyState.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Sheet from '../../ui/Sheet.vue'
import Skeleton from '../../ui/Skeleton.vue'
import StatusDot from '../../ui/StatusDot.vue'
import Tabs from '../../ui/Tabs.vue'
import AddGroupDialog from './AddGroupDialog.vue'
import GroupHeader from './GroupHeader.vue'
import GroupList from './GroupList.vue'
import { groupTabs, isGroupTab, lastGroupTab, type GroupTab } from './route'
import { statusTones } from './status'
import LiveTab from './live/LiveTab.vue'
import SessionTab from './session/SessionTab.vue'
import SettingsTab from './settings/SettingsTab.vue'
import LearningTab from './learning/LearningTab.vue'
import MemoryTab from './memory/MemoryTab.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const wide = useMediaQuery('(min-width: 1024px)')
const picking = ref(false)
const adding = ref(false)

// Old tabs inside a workbench tab hide their own page title.
provide('embedded-page', true)

const scenes = computed(() => (host.state?.scenes ?? []) as HostScene[])
const { scene, current } = useCurrentScene()
const tab = computed<GroupTab>(() => {
  const { scene: first, tab: second } = route.params
  if (isGroupTab(second)) return second
  return isGroupTab(first) ? first : lastGroupTab.value
})
const tabs = computed(() => groupTabs.map((value) => ({ value, label: t(`groups.tabs.${value}`) })))

// One canonical address per view: /groups/<scene>/<tab>.
watch(
  [scene, tab, () => route.params.scene, () => route.params.tab],
  ([value, name, first, second]) => {
    lastGroupTab.value = name
    if (value && (first !== value || second !== name)) {
      void router.replace({ name: 'groups', params: { scene: value, tab: name }, query: route.query })
    }
  },
  { immediate: true },
)

function select(value: string) {
  picking.value = false
  if (value === scene.value) return
  // The inner tab of an old page carries over; item ids belong to the previous group.
  const inner = typeof route.query.tab === 'string' ? { tab: route.query.tab } : {}
  void router.push({ name: 'groups', params: { scene: value, tab: tab.value }, query: inner })
}
const selectedTab = computed({
  get: () => tab.value,
  set: (value: GroupTab) => void router.push({ name: 'groups', params: { scene: scene.value, tab: value } }),
})

function addFromSheet() {
  picking.value = false
  adding.value = true
}

const dirty = reactive({ settings: false, learning: false, memory: false })
useUnsavedChanges(
  computed(() => Object.values(dirty).some(Boolean)),
  { onDiscard: () => Object.assign(dirty, { settings: false, learning: false, memory: false }) },
)

// Quiet hours and the hourly speaking limit end without an event; read the state again when one does.
let timer: ReturnType<typeof setTimeout> | undefined
watch(
  scenes,
  (items) => {
    clearTimeout(timer)
    const next = Math.min(...items.map((item) => item.chat_status.changes_at ?? Infinity))
    if (Number.isFinite(next)) {
      timer = setTimeout(readHostState, Math.min(Math.max(0, next * 1000 - Date.now()) + 1000, 2 ** 31 - 1))
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => clearTimeout(timer))
// A sent expression can reach the speaking limit.
useHostEvents(readHostState, { types: ['message.sent'], minInterval: 2000 })
</script>

<template>
  <div class="min-w-0">
  <Skeleton v-if="!host.state && !host.stateError" :lines="6" />
  <ErrorNote v-else-if="!host.state" :error="host.stateError" :retry="readHostState" />
  <EmptyState v-else-if="!scenes.length" :title="t('groups.empty')">
    <Button variant="primary" :icon="Plus" @click="adding = true">{{ t('groups.add') }}</Button>
  </EmptyState>
  <div v-else class="grid min-w-0 items-start gap-6 lg:grid-cols-[264px_minmax(0,1fr)]">
    <aside
      v-if="wide"
      class="sticky top-20 flex max-h-[calc(100dvh-6.5rem)] min-h-0 flex-col border-r border-line pr-4"
    >
      <GroupList :scenes="scenes" :selected="scene" @select="select" @add="adding = true" />
    </aside>
    <button
      v-else
      type="button"
      class="flex w-full cursor-pointer items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2 text-left transition-colors hover:border-line-strong focus-visible:focus-ring"
      :aria-label="t('groups.pick')"
      @click="picking = true"
    >
      <span class="flex" aria-hidden="true"><Avatar :name="groupLabel(scene)" shape="square" :size="28" /></span>
      <span class="min-w-0 flex-1 truncate text-base font-medium">{{ groupLabel(scene) }}</span>
      <StatusDot v-if="current" :tone="statusTones[current.chat_status.status]" />
      <ChevronsUpDown :size="16" class="shrink-0 text-muted" aria-hidden="true" />
    </button>

    <section v-if="current" class="flex min-w-0 flex-col gap-4">
      <GroupHeader :item="current" />
      <Tabs v-model="selectedTab" :items="tabs" :label="groupLabel(scene)">
        <template #[tab]>
          <div :key="`${scene}:${tab}`" class="grid min-w-0 gap-4">
            <LiveTab v-if="tab === 'live'" :scene="scene" :time-zone="current.timezone" :persona="current.persona.name" />
            <SessionTab v-else-if="tab === 'session'" :scene="scene" :time-zone="current.timezone" />
            <MemoryTab
              v-else-if="tab === 'memory'"
              :scene="scene"
              :time-zone="current.timezone"
              @dirty="(value: boolean) => (dirty.memory = value)"
            />
            <TasksPage v-else-if="tab === 'tasks'" />
            <LearningTab
              v-else-if="tab === 'learning'"
              :scene="scene"
              :time-zone="current.timezone"
              @dirty="(value: boolean) => (dirty.learning = value)"
            />
            <SettingsTab
              v-else
              :scene="scene"
              :time-zone="current.timezone"
              @dirty="(value: boolean) => (dirty.settings = value)"
            />
          </div>
        </template>
      </Tabs>
    </section>
  </div>

  <Sheet v-model:open="picking" :title="t('groups.pick')" side="bottom">
    <GroupList :scenes="scenes" :selected="scene" class="pb-2" @select="select" @add="addFromSheet" />
  </Sheet>
  <AddGroupDialog v-model:open="adding" @added="select" />
  </div>
</template>
