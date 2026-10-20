<script setup>
import { computed, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { useUnsavedChanges } from '../../../composables/useUnsavedChanges.js'
import HostPage from '../../ui/HostPage.vue'
import PageTabs from '../../ui/PageTabs.vue'
import McpSection from './McpSection.vue'
import WebServicesSection from './WebServicesSection.vue'
import WorkerSection from './WorkerSection.vue'
import BrowserSection from './BrowserSection.vue'

const route = useRoute()
// Tools and skills are allowed per role, on the role's detail page.
const tabs = [['mcp', 'MCP 服务'], ['web', '网页'], ['tasks', '独立任务']]
const tab = computed(() => tabs.some(([key]) => key === route.query.tab) ? route.query.tab : 'mcp')
const dirty = reactive({})
useUnsavedChanges(computed(() => Object.values(dirty).some(Boolean)), { onDiscard: () => { for (const key of Object.keys(dirty)) dirty[key] = false } })
</script>

<template>
  <HostPage title="能力" :wide="tab === 'mcp'">
    <PageTabs :tabs="tabs" :model-value="tab" label="能力分类" :clear="['item']" />
    <McpSection v-if="tab === 'mcp'" @dirty="value => dirty.mcp = value" />
    <WebServicesSection v-else-if="tab === 'web'" @dirty="value => dirty.web = value" />
    <template v-else-if="tab === 'tasks'">
      <WorkerSection @dirty="value => dirty.worker = value" />
      <BrowserSection @dirty="value => dirty.browser = value" />
    </template>
  </HostPage>
</template>
