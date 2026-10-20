<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import Tabs from '../../../ui/Tabs.vue'
import HealthTab from './HealthTab.vue'
import LogsTab from './LogsTab.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
// Old links say tab=system or tab=turns; both open the log.
const tab = computed({
  get: () => (route.query.tab === 'health' ? 'health' : 'system'),
  set: (value: string) => void router.replace({ query: { ...route.query, tab: value } }),
})
const tabs = computed(() => [
  { value: 'system', label: t('logs.tabs.system') },
  { value: 'health', label: t('logs.tabs.health') },
])
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <Tabs v-model="tab" :items="tabs" :label="t('shell.pages.systemLogs')" />
    <KeepAlive>
      <HealthTab v-if="tab === 'health'" />
      <LogsTab v-else />
    </KeepAlive>
  </div>
</template>
