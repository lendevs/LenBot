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
import SegmentedControl from '../../ui/SegmentedControl.vue'
import { confirm } from '../../ui/confirm'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

const { t } = useI18n()
const router = useRouter()
const { online, status, platform } = useConnectionStatus()
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
    title: t('overview.status.disconnectTitle', { platform: platform.value }),
    message: t('overview.status.disconnectMessage'),
    confirmLabel: t('overview.status.disconnect', { platform: platform.value }),
    tone: 'danger',
  })
  if (sure) disconnect.mutate()
}

const anyChat = computed(() => state.value.scenes.some((item) => item.chat_enabled))
const allChat = useMutation({
  mutationFn: (enabled: boolean) => overviewApi.setAllChat(enabled),
  onSuccess: (result) =>
    toast.success(t(result.enabled ? 'overview.status.allResumed' : 'overview.status.allPaused')),
  onError: failed(t('overview.status.allFailed')),
  onSettled: after,
})

const hold = useMutation({
  mutationFn: (enabled: boolean) => overviewApi.setSendHold(enabled),
  onError: failed(t('overview.status.holdFailed')),
  onSettled: after,
})
const sendMode = computed({
  get: () =>
    hold.isPending.value ? (hold.variables.value ? 'hold' : 'send') : state.value.send_hold ? 'hold' : 'send',
  set: (value: 'send' | 'hold') => hold.mutate(value === 'hold'),
})
const sendOptions = computed(() => [
  { value: 'send' as const, label: t('overview.status.sendReal', { platform: platform.value }) },
  { value: 'hold' as const, label: t('shell.status.simulated') },
])

const delivery = computed(() => {
  const value = state.value
  if (value.delivery === 'telegram') return t('overview.status.deliveryTelegram')
  if (value.delivery !== 'onebot') return t('shell.status.simulated')
  return value.send_hold ? t('overview.status.deliveryHeld') : t('overview.status.deliveryReal')
})
const note = computed(() => {
  const value = connection.value
  if (value.status === 'stopped' && value.disconnect_requested) return t('overview.status.notes.disconnected')
  const key = `overview.status.notes.${value.status}`
  return ['connection_failed', 'failed', 'stopped', 'waiting_connection'].includes(value.status)
    ? t(key, { platform: platform.value })
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
          label: t('overview.status.disconnect', { platform: platform.value }),
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
  <section class="flex flex-col gap-4 rounded-xl border border-line bg-surface p-5 shadow-card">
    <div class="flex flex-wrap items-center gap-x-5 gap-y-4">
      <span class="relative shrink-0">
        <img :src="markUrl" alt="" class="size-13 rounded-[14px]" />
        <span
          class="absolute -right-1 -bottom-1 size-3.5 rounded-full border-2 border-surface"
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
      <div class="min-w-0 flex-1 basis-56">
        <h2
          class="text-xl font-semibold"
          :class="!online && (status.tone === 'error' ? 'text-error' : 'text-warning')"
        >
          {{ online ? t('overview.status.online') : status.text }}
        </h2>
        <p class="mt-0.5 text-sm text-muted [overflow-wrap:anywhere]">
          {{
            [
              state.bot_id,
              delivery,
              t('overview.status.groups', { n: state.scenes.length }, state.scenes.length),
            ]
              .filter(Boolean)
              .join(' · ')
          }}
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
          {{ t('overview.status.connect', { platform }) }}
        </Button>
        <SegmentedControl
          v-if="state.delivery === 'onebot'"
          v-model="sendMode"
          :options="sendOptions"
          size="sm"
          :disabled="hold.isPending.value"
          :label="t('overview.status.sendMode')"
        />
        <Button
          v-if="state.scenes.length"
          size="sm"
          :icon="anyChat ? Pause : Play"
          :loading="allChat.isPending.value"
          :disabled="!connection.accepting"
          @click="allChat.mutate(!anyChat)"
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
