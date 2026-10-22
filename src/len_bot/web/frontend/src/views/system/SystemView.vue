<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import Tabs from '../../ui/Tabs.vue'
import AccountTab from './AccountTab.vue'
import AdvancedTab from './AdvancedTab.vue'
import ChatTab from './ChatTab.vue'
import ConnectionTab from './ConnectionTab.vue'
import PermissionsTab from './PermissionsTab.vue'
import PromptsTab from './PromptsTab.vue'
import RetentionTab from './RetentionTab.vue'
import UpdatesTab from './UpdatesTab.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const tabNames = [
  'connection',
  'permissions',
  'chat',
  'account',
  'retention',
  'prompts',
  'updates',
  'advanced',
] as const
type Tab = (typeof tabNames)[number]
const tab = computed<Tab>({
  get: () =>
    (tabNames as readonly string[]).includes(route.query.tab as string)
      ? (route.query.tab as Tab)
      : 'connection',
  set: (value) => void router.replace({ query: { ...route.query, tab: value } }),
})
const tabs = computed(() => tabNames.map((value) => ({ value, label: t(`system.tabs.${value}`) })))
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <Tabs v-model="tab" :items="tabs" :label="t('shell.pages.systemSettings')" />
    <KeepAlive>
      <ConnectionTab v-if="tab === 'connection'" />
      <PermissionsTab v-else-if="tab === 'permissions'" />
      <ChatTab v-else-if="tab === 'chat'" />
      <AccountTab v-else-if="tab === 'account'" />
      <RetentionTab v-else-if="tab === 'retention'" />
      <PromptsTab v-else-if="tab === 'prompts'" />
      <UpdatesTab v-else-if="tab === 'updates'" />
      <AdvancedTab v-else />
    </KeepAlive>
  </div>
</template>
