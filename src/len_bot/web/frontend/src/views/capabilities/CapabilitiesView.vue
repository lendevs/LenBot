<script setup lang="ts">
import { computed, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import { useUnsavedChanges } from '../../composables/useUnsavedChanges'
import Tabs from '../../ui/Tabs.vue'
import McpTab from './McpTab.vue'
import SkillsTab from './SkillsTab.vue'
import WebTab from './WebTab.vue'
import WorkerTab from './WorkerTab.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const tabNames = ['mcp', 'skills', 'web', 'tasks'] as const
type Tab = (typeof tabNames)[number]
const tab = computed<Tab>({
  get: () =>
    (tabNames as readonly string[]).includes(route.query.tab as string) ? (route.query.tab as Tab) : 'mcp',
  set: (value) => {
    const query: LocationQueryRaw = { tab: value }
    if (value === 'mcp' && typeof route.query.item === 'string') query.item = route.query.item
    if (value === 'skills' && typeof route.query.scene === 'string') query.scene = route.query.scene
    void router.replace({ query })
  },
})
const dirty = reactive<Record<Tab, boolean>>({ mcp: false, skills: false, web: false, tasks: false })
useUnsavedChanges(
  computed(() => Object.values(dirty).some(Boolean)),
  { keep: ['tab', 'item', 'scene'] },
)
const tabs = computed(() =>
  tabNames.map((value) => ({
    value,
    label: t(`capabilities.tabs.${value}`),
    dot: dirty[value] ? ('warning' as const) : undefined,
  })),
)
</script>

<template>
  <div class="flex min-w-0 flex-col gap-6 pb-2">
    <Tabs v-model="tab" :items="tabs" :label="t('shell.pages.capabilities')" />
    <Transition name="ui-tab" mode="out-in">
      <KeepAlive>
        <McpTab v-if="tab === 'mcp'" key="mcp" @dirty="(value) => (dirty.mcp = value)" />
        <SkillsTab v-else-if="tab === 'skills'" key="skills" />
        <WebTab v-else-if="tab === 'web'" key="web" @dirty="(value) => (dirty.web = value)" />
        <WorkerTab v-else key="tasks" @dirty="(value) => (dirty.tasks = value)" />
      </KeepAlive>
    </Transition>
  </div>
</template>
