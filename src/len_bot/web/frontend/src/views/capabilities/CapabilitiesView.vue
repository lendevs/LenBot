<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import Tabs from '../../ui/Tabs.vue'
import BrowserTab from './BrowserTab.vue'
import McpTab from './McpTab.vue'
import SkillsTab from './SkillsTab.vue'
import WebTab from './WebTab.vue'
import WorkerTab from './WorkerTab.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const tabNames = ['mcp', 'skills', 'web', 'tasks', 'browser'] as const
type Tab = (typeof tabNames)[number]
const tab = computed<Tab>({
  get: () =>
    (tabNames as readonly string[]).includes(route.query.tab as string) ? (route.query.tab as Tab) : 'mcp',
  set: (value) => void router.replace({ query: { ...route.query, tab: value } }),
})
const tabs = computed(() => tabNames.map((value) => ({ value, label: t(`capabilities.tabs.${value}`) })))
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <Tabs v-model="tab" :items="tabs" :label="t('shell.pages.capabilities')" />
    <KeepAlive>
      <McpTab v-if="tab === 'mcp'" />
      <SkillsTab v-else-if="tab === 'skills'" />
      <WebTab v-else-if="tab === 'web'" />
      <WorkerTab v-else-if="tab === 'tasks'" />
      <BrowserTab v-else />
    </KeepAlive>
  </div>
</template>
