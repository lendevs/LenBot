<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import Tabs, { type TabItem } from '../../../ui/Tabs.vue'
import HealthTab from './HealthTab.vue'
import LogsTab from './LogsTab.vue'

type Tab = 'system' | 'health'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
// Old links say tab=system or tab=turns; both open the log.
const tab = computed<Tab>({
  get: () => (route.query.tab === 'health' ? 'health' : 'system'),
  set: (value) => void router.replace({ query: { ...route.query, tab: value } }),
})
const tabs = computed<TabItem<Tab>[]>(() => [
  { value: 'system', label: t('logs.tabs.system') },
  { value: 'health', label: t('logs.tabs.health') },
])
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5 pb-2">
    <Tabs v-model="tab" :items="tabs" :label="t('shell.pages.systemLogs')" />
    <Transition name="ui-tab" mode="out-in">
      <KeepAlive>
        <HealthTab v-if="tab === 'health'" key="health" />
        <LogsTab v-else key="system" />
      </KeepAlive>
    </Transition>
  </div>
</template>
