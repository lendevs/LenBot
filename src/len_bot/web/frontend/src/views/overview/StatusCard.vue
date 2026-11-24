<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useMutation } from '@tanstack/vue-query'
import { Ellipsis, Pause, Play, PlugZap, Settings, Unplug } from '@lucide/vue'
import type { HostState } from '../../api/host'
import { overviewApi } from '../../api/overview'
import markUrl from '../../assets/lenbot-mark-tile.svg'
import { host, readHostState } from '../../api/hostStore'
import { useConnectionStatus } from '../../layouts/shell/status'
import Button from '../../ui/Button.vue'
import DropdownMenu, { type MenuEntry } from '../../ui/DropdownMenu.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import IconButton from '../../ui/IconButton.vue'
import StatusDot from '../../ui/StatusDot.vue'
import { confirm } from '../../ui/confirm'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

const { t, te } = useI18n()
const router = useRouter()
const { online, status } = useConnectionStatus()
const state = computed(() => host.state as HostState)
const connection = computed(() => state.value.connection)

const failed = (title: string) => (error: unknown) =>
  toast.error(title, { detail: describeError(error, t('ui.error.network')).message })
const after = () => void readHostState()

const connect = useMutation({
  mutationFn: overviewApi.connect,
  onError: failed(t('overview.status.connectFailed')),
  onSettled: after,
})
const disconnect = useMutation({
  mutationFn: overviewApi.disconnect,
  onError: failed(t('overview.status.disconnectFailed')),
  onSettled: after,
})
async function askDisconnect() {
  const sure = await confirm({
    title: t('overview.status.disconnectTitle'),
    message: t('overview.status.disconnectMessage'),
    confirmLabel: t('overview.status.disconnect'),
    tone: 'danger',
  })
  if (sure) disconnect.mutate()
}

const openScenes = computed(() => state.value.scenes.filter((item) => item.scene_open))
const anyChat = computed(() => openScenes.value.some((item) => item.chat_enabled))
const allChat = useMutation({
  mutationFn: (enabled: boolean) => overviewApi.setAllChat(enabled),
  onSuccess: (result) =>
    toast.success(t(result.enabled ? 'overview.status.allResumed' : 'overview.status.allPaused')),
  onError: failed(t('overview.status.allFailed')),
  onSettled: after,
})
async function toggleAllChat() {
  if (anyChat.value) {
    allChat.mutate(false)
    return
  }
  const pluginsOnly = state.value.scenes.filter((item) => !item.chat_enabled).length
  if (pluginsOnly > 0) {
    const sure = await confirm({
      title: t('overview.status.resumeAllTitle'),
      message: t('overview.status.resumeAllMessage', { n: pluginsOnly }, pluginsOnly),
      confirmLabel: t('overview.status.resumeAll'),
    })
    if (!sure) return
  }
  allChat.mutate(true)
}

const isSimulated = computed(() => state.value.delivery === 'simulated')
const platforms = computed(() =>
  Object.entries(connection.value.platforms ?? {}).map(([name, connected]) => ({
    name,
    label: te(`chatPlatforms.${name}`) ? t(`chatPlatforms.${name}`) : name,
    connected: Boolean(connected),
  })),
)
const showPlatforms = computed(() => platforms.value.length >= 2)

const note = computed(() => {
  const value = connection.value
  if (value.disconnect_requested && ['running', 'stopped'].includes(value.status))
    return t(`overview.status.notes.${value.status === 'running' ? 'disconnected' : 'stopped'}`)
  const key = `overview.status.notes.${value.status}`
  return ['connection_failed', 'failed', 'stopped', 'waiting_connection'].includes(value.status)
    ? t(key)
    : null
})
const menu = computed<MenuEntry[]>(() => [
  {
    label: t('overview.status.settings'),
    icon: Settings,
    select: () => void router.push({ name: 'host-system', query: { tab: 'connection' } }),
  },
  ...(connection.value.can_disconnect
    ? [
        { type: 'separator' as const },
        {
          label: t('overview.status.disconnect'),
          icon: Unplug,
          danger: true,
          disabled: disconnect.isPending.value,
          select: () => void askDisconnect(),
        },
      ]
    : []),
])
</script>

<template>
  <section class="flex flex-col gap-4 border-b border-line pb-6">
    <div class="flex flex-wrap items-center gap-x-4 gap-y-3">
      <span class="relative shrink-0">
        <img :src="markUrl" alt="" class="size-12 rounded-xl" />
        <span
          class="absolute -right-1 -bottom-1 size-3.5 rounded-full border-2 border-page"
          :class="
            online
              ? 'animate-pulse-dot bg-success text-success'
              : status.tone === 'error'
                ? 'bg-error'
                : 'bg-warning'
          "
          aria-hidden="true"
        />
      </span>
      <div class="min-w-0 flex-1 basis-52">
        <h2
          class="text-xl font-semibold tracking-tight"
          :class="online ? 'text-ink' : status.tone === 'error' ? 'text-error' : 'text-warning'"
        >
          {{ online ? t('overview.status.online') : status.text }}
        </h2>
        <p
          class="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted tabular [overflow-wrap:anywhere]"
        >
          <span v-if="state.bot_id" class="font-mono text-xs text-muted">{{ state.bot_id }}</span>
          <span v-if="state.bot_id" aria-hidden="true">·</span>
          <span>{{ t('overview.status.groups', { n: state.scenes.length }, state.scenes.length) }}</span>
          <template v-if="showPlatforms">
            <span aria-hidden="true">·</span>
            <span
              v-for="item in platforms"
              :key="item.name"
              class="inline-flex items-center gap-1.5 text-xs text-muted"
              :title="
                t(item.connected ? 'overview.status.platformOnline' : 'overview.status.platformOffline', {
                  name: item.label,
                })
              "
            >
              <StatusDot
                :tone="item.connected ? 'success' : status.tone === 'error' ? 'error' : 'warning'"
                :label="
                  t(item.connected ? 'overview.status.platformOnline' : 'overview.status.platformOffline', {
                    name: item.label,
                  })
                "
              />
              <span>{{ item.label }}</span>
            </span>
          </template>
          <template v-if="isSimulated">
            <span aria-hidden="true">·</span>
            <span class="inline-flex items-center gap-1.5 text-xs text-muted">
              <StatusDot tone="info" />
              <span>{{ t('overview.status.simulated') }}</span>
            </span>
          </template>
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <Button
          v-if="connection.can_connect || connect.isPending.value"
          variant="primary"
          :icon="PlugZap"
          :loading="connect.isPending.value"
          @click="connect.mutate()"
        >
          {{ t('overview.status.connect') }}
        </Button>
        <Button
          v-if="state.scenes.length"
          size="sm"
          :icon="anyChat ? Pause : Play"
          :loading="allChat.isPending.value"
          :disabled="!connection.accepting || !openScenes.length"
          @click="void toggleAllChat()"
        >
          {{ anyChat ? t('overview.status.pauseAll') : t('overview.status.resumeAll') }}
        </Button>
        <DropdownMenu :items="menu">
          <IconButton :icon="Ellipsis" :label="t('overview.status.more')" variant="secondary" size="sm" />
        </DropdownMenu>
      </div>
    </div>
    <p v-if="note" class="text-sm text-ink-2">{{ note }}</p>
    <ErrorNote
      v-if="connection.last_error"
      :title="t('overview.status.lastError')"
      :error="connection.last_error"
    />
  </section>
</template>
