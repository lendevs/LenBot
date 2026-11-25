<script setup lang="ts">
import { computed, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useMediaQuery } from '@vueuse/core'
import Tabs, { type TabItem } from '../../ui/Tabs.vue'
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

const dirtyTabs = reactive<Partial<Record<Tab, boolean>>>({})
function setDirty(name: Tab, value: boolean) {
  dirtyTabs[name] = value
}

const tab = computed<Tab>({
  get: () =>
    (tabNames as readonly string[]).includes(route.query.tab as string)
      ? (route.query.tab as Tab)
      : 'connection',
  set: (value) => {
    if (value === tab.value) return
    const { item: _item, ...rest } = route.query
    void router.replace({ query: { ...rest, tab: value } })
  },
})
const tabs = computed<TabItem<Tab>[]>(() =>
  tabNames.map((value) => ({
    value,
    label: t(`system.tabs.${value}`),
    dot: dirtyTabs[value] ? 'warning' : false,
  })),
)
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5 pb-2 lg:flex-row lg:items-start lg:gap-8">
    <Tabs
      v-model="tab"
      :items="tabs"
      :orientation="wide ? 'vertical' : 'horizontal'"
      :label="t('shell.pages.systemSettings')"
      class="lg:sticky lg:top-20 lg:shrink-0"
    />
    <div class="min-w-0 flex-1">
      <Transition name="ui-tab" mode="out-in">
        <KeepAlive>
          <ConnectionTab
            v-if="tab === 'connection'"
            key="connection"
            @dirty="(value: boolean) => setDirty('connection', value)"
          />
          <PermissionsTab
            v-else-if="tab === 'permissions'"
            key="permissions"
            @dirty="(value: boolean) => setDirty('permissions', value)"
          />
          <ChatTab
            v-else-if="tab === 'chat'"
            key="chat"
            @dirty="(value: boolean) => setDirty('chat', value)"
          />
          <AccountTab
            v-else-if="tab === 'account'"
            key="account"
            @dirty="(value: boolean) => setDirty('account', value)"
          />
          <RetentionTab
            v-else-if="tab === 'retention'"
            key="retention"
            @dirty="(value: boolean) => setDirty('retention', value)"
          />
          <PromptsTab
            v-else-if="tab === 'prompts'"
            key="prompts"
            @dirty="(value: boolean) => setDirty('prompts', value)"
          />
          <UpdatesTab v-else-if="tab === 'updates'" key="updates" />
          <AdvancedTab v-else key="advanced" @dirty="(value: boolean) => setDirty('advanced', value)" />
        </KeepAlive>
      </Transition>
    </div>
  </div>
</template>
