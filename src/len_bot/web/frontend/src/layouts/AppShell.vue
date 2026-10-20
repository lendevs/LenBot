<script setup lang="ts">
import { computed, onMounted, provide, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useMediaQuery } from '@vueuse/core'
import { TooltipProvider } from 'reka-ui'
import { Bell, Menu, PanelLeftClose, PanelLeftOpen, RotateCw, Search } from '@lucide/vue'
import { logout, useAuth } from '../composables/useAuth'
import { useCurrentScene } from '../composables/useCurrentScene'
import {
  host,
  readHostState,
  readOverview,
  readPendingRestart,
  readSceneTitles,
  readUpdates,
} from '../api/hostStore'
import { openRestart, restartFlow } from './shell/restart'
import { useHostEvents } from '../realtime/hostEvents'
import { currentLocale } from '../i18n'
import { streamRetryIn, streamStatus, reconnectStream } from '../realtime/stream'
import Badge from '../ui/Badge.vue'
import Button from '../ui/Button.vue'
import ConfirmHost from '../ui/ConfirmHost.vue'
import ErrorNote from '../ui/ErrorNote.vue'
import IconButton from '../ui/IconButton.vue'
import Kbd from '../ui/Kbd.vue'
import Sheet from '../ui/Sheet.vue'
import Tabs from '../ui/Tabs.vue'
import Toaster from '../ui/Toaster.vue'
import { confirm } from '../ui/confirm'
import AccountMenu from './shell/AccountMenu.vue'
import CommandPalette from './shell/CommandPalette.vue'
import RestartDialog from './shell/RestartDialog.vue'
import Sidebar from './shell/Sidebar.vue'
import { groupLabel } from './shell/scenes'
import { useConnectionStatus } from './shell/status'
import { areaOf, groupOf, scopedRoutes, sectionKey } from './nav'
import { useAttention } from '../views/overview/attention'

interface Restart {
  sections: string[]
  scenes: string[]
  plugins: { name: string }[]
  personas: { name: string }[]
  error?: unknown
}

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuth()
const wide = useMediaQuery('(min-width: 1024px)')
const drawer = ref(false)
const palette = ref(false)
const leaving = ref(false)
const logoutError = ref<unknown>(null)
const { scene } = useCurrentScene()

const COLLAPSED = 'lenbot.sidebar.collapsed'
function savedCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED) === '1'
  } catch {
    return false
  }
}
const collapsed = ref(savedCollapsed())
watch(collapsed, (value) => {
  try {
    localStorage.setItem(COLLAPSED, value ? '1' : '0')
  } catch {
    // Storage refused: the choice lasts for this tab.
  }
})

const events = useHostEvents(readHostState, { types: ['host.state', 'host.changed'] })
// Today's totals change with every message; the server caches them for five seconds, so reading more often is waste.
useHostEvents(readOverview, {
  types: ['host.changed', 'message.received', 'message.sent', 'turn.ended'],
  minInterval: 10000,
})
provide('host-events', events)

const area = computed(() => areaOf(route.name))
const group = computed(() => groupOf(area.value))
const subpage = computed(() => area.value?.pages.find((page) => page.route === route.name))
const tabs = computed(() =>
  (area.value?.pages ?? []).map((page) => ({ value: page.route, label: t(page.label) })),
)
const tab = computed({
  get: () => String(route.name),
  set: (name: string) => {
    void router.push({ name, query: scopedRoutes.has(name) && scene.value ? { scene: scene.value } : {} })
  },
})

const { status } = useConnectionStatus()

const listFormat = computed(() => new Intl.ListFormat(currentLocale.value, { type: 'conjunction' }))
const restart = computed(() => host.restart as Restart | null)
const restartItems = computed(() => {
  const value = restart.value
  if (!value || value.error) return []
  return [
    ...new Set([
      ...value.sections.map((section) => t(sectionKey(section))),
      ...value.scenes.map(groupLabel),
      ...value.plugins.map((item) => t('shell.restart.plugin', { name: item.name })),
      ...value.personas.map((item) => t('shell.restart.persona', { name: item.name })),
    ]),
  ]
})
const { count: attention } = useAttention()
const newer = computed(() => {
  const updates = host.updates as { check?: { update_available?: boolean; latest?: string } } | null
  return updates?.check?.update_available ? (updates.check.latest ?? '') : ''
})
const flagged = computed(() => {
  const overview = host.overview as { memory_index?: { needs_rebuild?: boolean } } | null
  return new Set(overview?.memory_index?.needs_rebuild ? ['groups'] : [])
})

function refresh() {
  readHostState()
  readPendingRestart()
  readOverview()
}
onMounted(() => {
  refresh()
  readUpdates()
  readSceneTitles()
})
watch(() => route.name, refresh)
// Cached names arrive at once; each new connection reads the names again.
watch(
  () => host.state?.connection.connected,
  (connected) => {
    if (connected) readSceneTitles()
  },
)
watch(
  () => route.fullPath,
  () => (drawer.value = false),
)

async function exit() {
  if (leaving.value) return
  const confirmed = await confirm({
    title: t('shell.account.logoutTitle'),
    message: t('shell.account.logoutMessage'),
    confirmLabel: t('shell.account.logout'),
  })
  if (!confirmed) return
  leaving.value = true
  logoutError.value = null
  try {
    await logout()
    if (useAuth().status === 'unauthenticated') await router.replace({ name: 'login' })
  } catch (error) {
    logoutError.value = error
  } finally {
    leaving.value = false
  }
}
</script>

<template>
  <TooltipProvider :delay-duration="400">
    <div class="flex min-h-dvh bg-page text-ink">
      <aside
        v-if="wide"
        class="sticky top-0 h-dvh shrink-0 border-r border-line bg-sidebar transition-[width] duration-250 ease-out"
        :class="collapsed ? 'w-16' : 'w-58'"
      >
        <Sidebar :collapsed="collapsed" :scene="scene" :flagged="flagged">
          <template #footer>
            <div class="shrink-0 border-t border-line p-2" :class="collapsed ? 'flex justify-center' : ''">
              <IconButton
                :icon="collapsed ? PanelLeftOpen : PanelLeftClose"
                :label="collapsed ? t('shell.nav.expand') : t('shell.nav.collapse')"
                size="sm"
                @click="collapsed = !collapsed"
              />
            </div>
          </template>
        </Sidebar>
      </aside>
      <Sheet v-else v-model:open="drawer" :title="t('shell.nav.label')" side="left" size="sm" hide-header>
        <div class="h-full bg-sidebar"><Sidebar :collapsed="false" :scene="scene" :flagged="flagged" /></div>
      </Sheet>

      <div class="flex min-w-0 flex-1 flex-col">
        <header
          class="sticky top-0 z-(--z-top) flex h-14 shrink-0 items-center gap-2 border-b border-line bg-page/85 px-3 backdrop-blur-md sm:px-6"
        >
          <IconButton
            v-if="!wide"
            :icon="Menu"
            :label="t('shell.nav.open')"
            :tooltip="false"
            @click="drawer = true"
          />
          <nav
            class="flex min-w-0 items-center gap-2 text-base max-sm:hidden"
            :aria-label="t('shell.nav.sections')"
          >
            <span v-if="group" class="text-muted">{{ t(group.label) }}</span>
            <span v-if="group" class="text-line-strong" aria-hidden="true">/</span>
            <strong class="truncate font-semibold">{{ area ? t(area.label) : '' }}</strong>
            <template v-if="subpage && area && area.pages[0]?.route !== subpage.route">
              <span class="text-line-strong" aria-hidden="true">/</span>
              <span class="truncate text-ink-2">{{ t(subpage.label) }}</span>
            </template>
          </nav>
          <div class="ml-auto flex items-center gap-1.5">
            <button
              type="button"
              class="inline-flex h-8 cursor-pointer items-center gap-2 rounded-md border border-line bg-fill px-2.5 text-sm text-muted transition-colors hover:border-line-strong hover:text-ink focus-visible:focus-ring"
              :aria-label="t('shell.search')"
              aria-keyshortcuts="Control+K Meta+K"
              @click="palette = true"
            >
              <Search :size="15" aria-hidden="true" />
              <span class="max-md:hidden">{{ t('shell.search') }}</span>
              <Kbd class="max-md:hidden">⌘K</Kbd>
            </button>
            <RouterLink
              v-if="newer"
              :to="{ name: 'host-system', query: { tab: 'updates' } }"
              class="link-plain inline-flex h-8 animate-rise items-center gap-2 rounded-full bg-brand-soft px-3 text-sm font-semibold text-primary hover:brightness-97 max-sm:hidden"
            >
              <span class="size-1.5 animate-pulse-dot rounded-full bg-brand text-brand" aria-hidden="true" />
              {{ t('shell.update', { version: newer }) }}
            </RouterLink>
            <Badge v-if="host.state?.delivery === 'simulated'" size="md" class="max-sm:hidden">
              {{ t('shell.status.simulated') }}
            </Badge>
            <button
              v-if="streamStatus !== 'open' && streamStatus !== 'idle'"
              type="button"
              class="inline-flex h-8 cursor-pointer items-center gap-2 rounded-full bg-warning-bg px-3 text-sm text-warning focus-visible:focus-ring"
              :title="t('shell.live.reconnect')"
              @click="reconnectStream"
            >
              <RotateCw
                :size="14"
                :class="streamStatus === 'connecting' && 'animate-spin'"
                aria-hidden="true"
              />
              <span class="max-sm:hidden">
                {{ streamStatus === 'connecting' ? t('shell.live.connecting') : t('shell.live.closed') }}
                <template v-if="streamStatus === 'closed' && streamRetryIn">
                  · {{ t('shell.live.retry', { n: streamRetryIn }) }}
                </template>
              </span>
            </button>
            <Badge :tone="status.tone" dot :pulse="status.tone === 'success'" size="md">
              {{ status.text }}
            </Badge>
            <span class="relative inline-flex">
              <IconButton
                :icon="Bell"
                :to="{ name: 'host-overview' }"
                :label="attention ? t('shell.attention.count', { n: attention }) : t('shell.attention.none')"
              />
              <span
                v-if="attention"
                class="pointer-events-none absolute -top-0.5 -right-0.5 inline-flex h-4 min-w-4 animate-[ui-pop-in_var(--dur-2)_var(--ease-spring)] items-center justify-center rounded-full bg-error px-1 text-[10px] font-semibold text-white tabular"
                aria-hidden="true"
              >
                {{ attention }}
              </span>
            </span>
            <AccountMenu
              :username="auth.user?.username ?? ''"
              :restart-disabled="restartFlow.waiting"
              :leaving="leaving"
              @restart="openRestart"
              @logout="exit"
            />
          </div>
        </header>

        <div v-if="tabs.length" class="shrink-0 px-3 sm:px-6">
          <Tabs v-model="tab" :items="tabs" :label="area ? t(area.label) : undefined" />
        </div>

        <main
          id="main-content"
          class="grid w-full min-w-0 content-start gap-4 px-3 pt-4 pb-10 sm:px-4 sm:pt-6 sm:pb-12 lg:px-8 lg:pt-8 lg:pb-16"
        >
          <ErrorNote v-if="logoutError" :title="t('shell.account.logoutFailed')" :error="logoutError" />
          <Transition name="ui-rise">
            <div
              v-if="restartItems.length"
              role="status"
              class="flex flex-wrap items-center gap-3 rounded-lg bg-info-bg px-4 py-2.5 text-sm text-ink-2"
            >
              <RotateCw :size="16" class="shrink-0 text-info" aria-hidden="true" />
              <span class="min-w-0 flex-1">
                {{ t('shell.restart.banner', { items: listFormat.format(restartItems) }) }}
              </span>
              <Button size="sm" :disabled="restartFlow.waiting" @click="openRestart">
                {{ t('shell.restart.action') }}
              </Button>
            </div>
          </Transition>
          <ErrorNote
            v-if="restart?.error"
            :title="t('shell.restart.unknown')"
            :error="restart.error"
            :retry="readPendingRestart"
          />
          <slot v-if="!restartFlow.waiting" />
        </main>
      </div>
    </div>
    <CommandPalette v-model:open="palette" :scene="scene" />
    <RestartDialog />
    <ConfirmHost />
    <Toaster />
  </TooltipProvider>
</template>
