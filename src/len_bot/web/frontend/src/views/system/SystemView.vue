<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useMediaQuery } from '@vueuse/core'
import { TabsList, TabsRoot, TabsTrigger } from 'reka-ui'
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
const wide = useMediaQuery('(min-width: 1024px)')
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
  <TabsRoot
    v-model="tab"
    :orientation="wide ? 'vertical' : 'horizontal'"
    class="grid min-w-0 items-start gap-6 pb-2 lg:grid-cols-[12rem_minmax(0,1fr)] lg:gap-8"
  >
    <TabsList
      :aria-label="t('shell.pages.systemSettings')"
      class="flex flex-wrap gap-1.5 lg:sticky lg:top-20 lg:flex-col lg:gap-0.5 lg:border-r lg:border-line lg:pr-4"
    >
      <TabsTrigger
        v-for="item in tabs"
        :key="item.value"
        :value="item.value"
        :class="
          tab === item.value
            ? 'bg-fill font-semibold text-ink max-lg:border-line-strong'
            : 'font-medium text-muted hover:bg-hover hover:text-ink max-lg:border-line max-lg:bg-surface'
        "
        class="inline-flex h-8 cursor-pointer items-center rounded-md px-2.5 text-sm whitespace-nowrap transition-colors outline-none focus-visible:focus-ring max-lg:border lg:h-9 lg:w-full lg:justify-start lg:px-3"
      >
        {{ item.label }}
      </TabsTrigger>
    </TabsList>
    <div class="min-w-0">
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
  </TabsRoot>
</template>
