<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import { useQueryClient } from '@tanstack/vue-query'
import { useMediaQuery } from '@vueuse/core'
import { ChevronsUpDown, Plus } from '@lucide/vue'
import type { HostScene } from '../../api/host'
import { keys } from '../../api/query'
import { useCurrentScene } from '../../composables/useCurrentScene'
import { useUnsavedChanges } from '../../composables/useUnsavedChanges'
import { useHostEvents } from '../../realtime/hostEvents'
import { host, readHostState } from '../../api/hostStore'
import { groupLabel, groupSecondaryId, isPrivateScene } from '../../layouts/shell/scenes'
import Avatar from '../../ui/Avatar.vue'
import Button from '../../ui/Button.vue'
import EmptyState from '../../ui/EmptyState.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Sheet from '../../ui/Sheet.vue'
import Skeleton from '../../ui/Skeleton.vue'
import Tabs from '../../ui/Tabs.vue'
import AddGroupDialog from './AddGroupDialog.vue'
import GroupHeader from './GroupHeader.vue'
import GroupList from './GroupList.vue'
import { groupTabs, isGroupTab, lastGroupTab, type GroupTab } from './route'

const LiveTab = defineAsyncComponent(() => import('./live/LiveTab.vue'))
const SessionTab = defineAsyncComponent(() => import('./session/SessionTab.vue'))
const SettingsTab = defineAsyncComponent(() => import('./settings/SettingsTab.vue'))
const LearningTab = defineAsyncComponent(() => import('./learning/LearningTab.vue'))
const MemoryTab = defineAsyncComponent(() => import('./memory/MemoryTab.vue'))
const ReferenceTab = defineAsyncComponent(() => import('./reference/ReferenceTab.vue'))
const TasksTab = defineAsyncComponent(() => import('./tasks/TasksTab.vue'))

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const client = useQueryClient()
const wide = useMediaQuery('(min-width: 1024px)')
const picking = ref(false)
const adding = ref(false)
const settingsKey = ref(0)

watch(wide, (value) => {
  if (value) picking.value = false
})

const scenes = computed(() => (host.state?.scenes ?? []) as HostScene[])
const { scene, current } = useCurrentScene()
// Learning runs in group chats only.
const supportsTab = (targetScene: string, name: GroupTab) =>
  name !== 'learning' || !isPrivateScene(targetScene)
const available = computed(() => groupTabs.filter((value) => supportsTab(scene.value, value)))
const tab = computed<GroupTab>(() => {
  const { scene: first, tab: second } = route.params
  const name = isGroupTab(second) ? second : isGroupTab(first) ? first : lastGroupTab.value
  return available.value.includes(name) ? name : 'live'
})
const tabs = computed(() => available.value.map((value) => ({ value, label: t(`groups.tabs.${value}`) })))

// Tracks a fallback redirect (e.g. private chat without learning → live) so it never overwrites `lastGroupTab`.
let fallbackTarget: string | null = null

// One canonical address per view: /groups/<scene>/<tab>.
watch(
  [scene, tab, () => route.params.scene, () => route.params.tab],
  ([value, name, first, second]) => {
    if (!value) return
    const requested = isGroupTab(second) ? second : isGroupTab(first) ? first : null
    const targetKey = `${value}:${name}`
    if (requested !== null && available.value.includes(requested)) {
      if (fallbackTarget === targetKey) fallbackTarget = null
      else lastGroupTab.value = requested
    } else if (requested !== null || !available.value.includes(lastGroupTab.value)) {
      fallbackTarget = targetKey
    }
    if (first !== value || second !== name) {
      void router.replace({ name: 'groups', params: { scene: value, tab: name }, query: route.query })
    }
  },
  { immediate: true },
)

async function select(value: string) {
  if (value === scene.value) {
    picking.value = false
    return
  }
  const preferred = lastGroupTab.value
  const supported = supportsTab(value, preferred)
  const nextTab: GroupTab = supported ? preferred : 'live'
  // Inner tab and timeline filter carry over; item ids belong to the previous group.
  const query: LocationQueryRaw = {}
  if (typeof route.query.tab === 'string') query.tab = route.query.tab
  if (typeof route.query.filter === 'string') query.filter = route.query.filter
  fallbackTarget = supported ? null : `${value}:${nextTab}`
  const failure = await router.push({ name: 'groups', params: { scene: value, tab: nextTab }, query })
  if (failure) {
    fallbackTarget = null
    return
  }
  picking.value = false
}
const selectedTab = computed({
  get: () => tab.value,
  set: (value: GroupTab) => {
    if (value === tab.value) return
    fallbackTarget = null
    void router.push({ name: 'groups', params: { scene: scene.value, tab: value } }).then((failure) => {
      if (!failure) lastGroupTab.value = value
    })
  },
})

function addFromSheet() {
  picking.value = false
  adding.value = true
}

const dirty = reactive({ settings: false, learning: false, memory: false, tasks: false })
useUnsavedChanges(
  computed(() => Object.values(dirty).some(Boolean)),
  {
    // Inner tabs and filters handle their own unsaved prompts or read-only views.
    keep: ['tab', 'id', 'kind', 'filter'],
    onDiscard: () => Object.assign(dirty, { settings: false, learning: false, memory: false, tasks: false }),
  },
)

function discardSettings() {
  dirty.settings = false
  settingsKey.value += 1
}

// Quiet hours and the hourly speaking limit end without an event; read the state again when one does.
let timer: ReturnType<typeof setTimeout> | undefined
watch(
  scenes,
  (items) => {
    clearTimeout(timer)
    const next = Math.min(...items.map((item) => item.chat_status.changes_at ?? Infinity))
    if (Number.isFinite(next)) {
      timer = setTimeout(
        () => {
          void readHostState()
          const affected = new Set(
            items
              .filter((item) => item.chat_status.changes_at !== null && item.chat_status.changes_at <= next)
              .map((item) => item.scene),
          )
          if (scene.value) affected.add(scene.value)
          for (const id of affected) void client.invalidateQueries({ queryKey: keys.scene.control(id) })
        },
        Math.min(Math.max(0, next * 1000 - Date.now()) + 1000, 2 ** 31 - 1),
      )
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
        class="sticky top-18 flex max-h-[calc(100dvh-5.5rem)] min-h-0 flex-col border-r border-line pr-4"
      >
        <GroupList :scenes="scenes" :selected="scene" @select="select" @add="adding = true" />
      </aside>
      <button
        v-else-if="!current"
        type="button"
        class="flex w-full cursor-pointer items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2 text-left transition-colors hover:border-line-strong focus-visible:focus-ring"
        :aria-label="t('groups.pick')"
        @click="picking = true"
      >
        <span class="flex" aria-hidden="true">
          <Avatar :name="groupLabel(scene)" shape="square" :size="28" />
        </span>
        <span class="min-w-0 flex-1 truncate text-base font-medium text-ink">{{ groupLabel(scene) }}</span>
        <span v-if="groupSecondaryId(scene)" class="shrink-0 font-mono text-xs text-muted tabular">
          {{ groupSecondaryId(scene) }}
        </span>
        <ChevronsUpDown :size="16" class="shrink-0 text-muted" aria-hidden="true" />
      </button>

      <section v-if="current" class="flex min-w-0 flex-col gap-4">
        <GroupHeader
          :item="current"
          :switchable="!wide"
          :settings-dirty="dirty.settings"
          @switch="picking = true"
          @discard-settings="discardSettings"
        />
        <Tabs v-model="selectedTab" :items="tabs" :label="groupLabel(scene)" />
        <Transition name="ui-tab" mode="out-in">
          <div :key="`${scene}:${tab}`" class="grid min-w-0 gap-4">
            <LiveTab
              v-if="tab === 'live'"
              :scene="scene"
              :time-zone="current.timezone"
              :persona="current.persona.name"
              :persona-path="current.persona_path"
            />
            <SessionTab v-else-if="tab === 'session'" :scene="scene" :time-zone="current.timezone" />
            <MemoryTab
              v-else-if="tab === 'memory'"
              :scene="scene"
              :time-zone="current.timezone"
              @dirty="(value: boolean) => (dirty.memory = value)"
            />
            <ReferenceTab v-else-if="tab === 'reference'" :scene="scene" />
            <TasksTab
              v-else-if="tab === 'tasks'"
              :scene="scene"
              :time-zone="current.timezone"
              @dirty="(value: boolean) => (dirty.tasks = value)"
            />
            <LearningTab
              v-else-if="tab === 'learning'"
              :scene="scene"
              :time-zone="current.timezone"
              @dirty="(value: boolean) => (dirty.learning = value)"
            />
            <SettingsTab
              v-else
              :key="settingsKey"
              :scene="scene"
              :time-zone="current.timezone"
              @dirty="(value: boolean) => (dirty.settings = value)"
            />
          </div>
        </Transition>
      </section>
    </div>

    <Sheet v-model:open="picking" :title="t('groups.pick')" side="bottom">
      <GroupList
        :scenes="scenes"
        :selected="scene"
        surface="raised"
        class="pb-2"
        @select="select"
        @add="addFromSheet"
      />
    </Sheet>
    <AddGroupDialog v-model:open="adding" @added="select" />
  </div>
</template>
