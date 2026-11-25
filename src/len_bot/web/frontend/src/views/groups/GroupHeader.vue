<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { useNow } from '@vueuse/core'
import {
  ArrowUpRight,
  Check,
  ChevronDown,
  ChevronsUpDown,
  Ellipsis,
  FlaskConical,
  Moon,
  RefreshCcw,
  Sun,
  UserRound,
} from '@lucide/vue'
import { hostApi, type HostScene } from '../../api/host'
import { keys } from '../../api/query'
import { host, readHostState } from '../../api/hostStore'
import { formatNumber } from '../../i18n/format'
import { groupLabel, groupSecondaryId, isPrivateScene, scenePlatform } from '../../layouts/shell/scenes'
import { useHostEvent } from '../../realtime/stream'
import Avatar from '../../ui/Avatar.vue'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import DropdownMenu, { type MenuEntry } from '../../ui/DropdownMenu.vue'
import IconButton from '../../ui/IconButton.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import StatusDot from '../../ui/StatusDot.vue'
import Switch from '../../ui/Switch.vue'
import { confirm } from '../../ui/confirm'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'
import QuietDialog from './QuietDialog.vue'
import { roleLabel, useRoleSwitch, useRoles } from './roleSwitch'
import { useSessionActions } from './session/useSessionActions'
import { formatQuietRemaining, statusTones, useStatusLabel } from './status'

const props = defineProps<{ item: HostScene; switchable?: boolean; settingsDirty?: boolean }>()
const emit = defineEmits<{ switch: []; discardSettings: [] }>()

const { t, te } = useI18n()
const router = useRouter()
const client = useQueryClient()
const statusLabel = useStatusLabel()
const openId = useId()
const quieting = ref(false)

const scene = computed(() => props.item.scene)
const name = computed(() => groupLabel(scene.value))
const groupId = computed(() => groupSecondaryId(scene.value))
const platform = computed(() => {
  const prefix = scenePlatform(scene.value)
  if (!prefix || prefix === 'onebot') return ''
  return te(`chatPlatforms.${prefix}`) ? t(`chatPlatforms.${prefix}`) : prefix
})
const members = computed(() => (host.members as Record<string, number>)[scene.value])
const memberText = computed(() =>
  members.value === undefined ? '' : t('groups.members', { n: formatNumber(members.value) }, members.value),
)
const accepting = computed(() => Boolean(host.state?.connection.accepting))

const control = useQuery({
  queryKey: computed(() => keys.scene.control(scene.value)),
  queryFn: ({ signal }) => hostApi.control(scene.value, signal),
})
useHostEvent('host.state', (event) => {
  if (event.scene === null || event.scene === scene.value)
    void client.invalidateQueries({ queryKey: keys.scene.control(scene.value) })
})

// Lightweight clock ticks only while temporary quiet or a timed status is active.
const { now, pause: pauseClock, resume: resumeClock } = useNow({ interval: 1000, controls: true })
const rawQuiet = computed(() => control.data.value?.temporary_quiet ?? null)
const temporaryQuiet = computed(() => {
  const quiet = rawQuiet.value
  return quiet && quiet.until * 1000 > now.value.getTime() ? quiet : null
})
const quietRemaining = computed(() =>
  temporaryQuiet.value ? formatQuietRemaining(temporaryQuiet.value.until, now.value.getTime()) : '',
)
const hasUpcomingExpiry = computed(() => {
  const nowMs = now.value.getTime()
  const quietUntil = rawQuiet.value?.until
  const statusUntil = props.item.chat_status.changes_at
  return (
    (quietUntil !== undefined && quietUntil * 1000 > nowMs) ||
    (statusUntil !== null && statusUntil * 1000 > nowMs)
  )
})
watch(hasUpcomingExpiry, (active) => (active ? resumeClock() : pauseClock()), { immediate: true })
watch(temporaryQuiet, (next, prev) => {
  // When temporary quiet reaches its deadline on the local clock, refresh host state and control at once.
  if (prev && !next && rawQuiet.value) {
    void readHostState()
    void client.invalidateQueries({ queryKey: keys.scene.control(scene.value) })
  }
})

const failed = (title: string) => (error: unknown) =>
  toast.error(title, { detail: describeError(error, t('ui.error.network')).message })

const chat = useMutation({
  mutationFn: (enabled: boolean) => hostApi.setChat(scene.value, enabled),
  onSuccess: (value, enabled) => {
    client.setQueryData(keys.scene.control(scene.value), value)
    toast.success(t(enabled ? 'groups.chatOn' : 'groups.chatOff', { name: name.value }))
  },
  onError: failed(t('groups.chatFailed')),
  onSettled: () => readHostState(),
})
const mode = computed({
  get: () =>
    (chat.isPending.value ? Boolean(chat.variables.value) : props.item.chat_enabled) ? 'chat' : 'plugins',
  set: (value: 'chat' | 'plugins') => chat.mutate(value === 'chat'),
})
const modes = computed(() => [
  { value: 'chat' as const, label: t('overview.groups.modeChat') },
  { value: 'plugins' as const, label: t('overview.groups.modePlugins') },
])

const open = useMutation({
  mutationFn: (enabled: boolean) => hostApi.setOpen(scene.value, enabled),
  onSuccess: (value, enabled) => {
    client.setQueryData(keys.scene.control(scene.value), value)
    toast.success(t(enabled ? 'groups.opened' : 'groups.closed', { name: name.value }))
  },
  onError: failed(t('groups.openFailed')),
  onSettled: () => readHostState(),
})
const opened = computed({
  get: () => (open.isPending.value ? Boolean(open.variables.value) : props.item.scene_open),
  set: (value: boolean) => open.mutate(value),
})

const resume = useMutation({
  mutationFn: () => hostApi.resume(scene.value),
  onSuccess: (value) => {
    client.setQueryData(keys.scene.control(scene.value), value)
    toast.success(t('groups.quiet.resumed'))
  },
  onError: failed(t('groups.quiet.failed')),
  onSettled: () => readHostState(),
})

const { starting, startSession } = useSessionActions(scene)

const { roles, usable } = useRoles()
const { switchRole, sending } = useRoleSwitch()
const currentRole = computed(() => roles.value.find((role) => role.path === props.item.persona_path))
const roleItems = computed<MenuEntry[]>(() => [
  { type: 'label', label: t('groups.role.switch') },
  ...usable.value.map((role) => ({
    label: roleLabel(role),
    icon: role === currentRole.value ? Check : UserRound,
    disabled: role === currentRole.value || Boolean(props.item.persona_switch) || sending(scene.value),
    select: () => void choose(role),
  })),
  ...(currentRole.value
    ? [
        { type: 'separator' as const },
        {
          label: t('groups.settings.role.edit'),
          icon: ArrowUpRight,
          select: () =>
            void router.push({ name: 'host-persona', query: { persona: currentRole.value!.key } }),
        },
      ]
    : []),
])
async function choose(role: (typeof usable.value)[number]) {
  if (props.settingsDirty) {
    const discard = await confirm({
      title: t('groups.settings.role.discard'),
      confirmLabel: t('common.discard'),
      tone: 'danger',
    })
    if (!discard) return
  }
  const confirmed = await confirm({
    title: t('groups.settings.role.title', { group: name.value, name: roleLabel(role) }),
    confirmLabel: t('groups.settings.role.action'),
    tone: 'primary',
  })
  if (!confirmed) return
  if (props.settingsDirty) emit('discardSettings')
  switchRole(scene.value, role)
}

const actions = computed<MenuEntry[]>(() => [
  temporaryQuiet.value
    ? {
        label: t('groups.quiet.resume'),
        icon: Sun,
        disabled: !accepting.value || resume.isPending.value,
        select: () => resume.mutate(),
      }
    : {
        label: t('groups.quiet.action'),
        icon: Moon,
        disabled: !accepting.value,
        select: () => (quieting.value = true),
      },
  {
    label: t('groups.newSession.action'),
    icon: RefreshCcw,
    disabled: starting.value,
    select: startSession,
  },
  { type: 'separator' },
  {
    label: t('groups.trial'),
    icon: FlaskConical,
    select: () => void router.push({ name: 'host-trials', query: { scene: scene.value } }),
  },
])
</script>

<template>
  <header class="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-x-4">
    <div class="flex min-w-0 flex-1 items-center gap-3.5 sm:min-w-64">
      <span class="flex max-sm:hidden" aria-hidden="true">
        <Avatar :name="name" shape="square" :size="42" />
      </span>
      <div class="min-w-0 flex-1">
        <h1 class="min-w-0 text-xl font-semibold text-ink max-sm:hidden">
          <button
            v-if="switchable"
            type="button"
            class="group -mx-1.5 -my-0.5 inline-flex max-w-full cursor-pointer items-center gap-2 rounded-md px-1.5 py-0.5 text-left transition-colors hover:bg-hover focus-visible:focus-ring"
            :aria-label="t('groups.pick')"
            @click="emit('switch')"
          >
            <span class="truncate">{{ name }}</span>
            <ChevronsUpDown
              :size="16"
              class="shrink-0 text-muted transition-colors group-hover:text-ink"
              aria-hidden="true"
            />
          </button>
          <span v-else class="block truncate">{{ name }}</span>
        </h1>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted sm:mt-0.5 sm:text-sm">
          <span class="inline-flex items-center gap-1.5 text-ink-2">
            <StatusDot :tone="statusTones[item.chat_status.status]" />
            {{ statusLabel(item.chat_status, item.timezone, now.getTime()) }}
          </span>
          <span v-if="temporaryQuiet" class="inline-flex items-center gap-1">
            <Badge tone="info">
              <span class="tabular">{{ t('groups.quiet.remaining', { time: quietRemaining }) }}</span>
            </Badge>
            <Button
              size="xs"
              variant="ghost"
              :icon="Sun"
              :loading="resume.isPending.value"
              :disabled="!accepting"
              @click="resume.mutate()"
            >
              {{ t('groups.quiet.resume') }}
            </Button>
          </span>
          <Badge v-if="isPrivateScene(scene)" size="sm">{{ t('groups.join.kinds.private') }}</Badge>
          <span v-if="platform" class="whitespace-nowrap">{{ platform }}</span>
          <span v-if="groupId" class="font-mono text-xs whitespace-nowrap tabular">{{ groupId }}</span>
          <span v-if="memberText" class="whitespace-nowrap tabular">{{ memberText }}</span>
          <DropdownMenu :items="roleItems" align="start">
            <button
              type="button"
              class="-mx-1.5 inline-flex min-w-0 cursor-pointer items-center gap-1 rounded-md px-1.5 py-0.5 text-ink-2 transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring pointer-coarse:min-h-9 pointer-coarse:px-2"
              :aria-label="t('groups.role.label', { name: item.persona.name })"
            >
              <UserRound :size="13" class="shrink-0 text-muted" aria-hidden="true" />
              <span class="truncate">{{ item.persona.name }}</span>
              <ChevronDown :size="13" class="shrink-0 text-muted" aria-hidden="true" />
            </button>
          </DropdownMenu>
          <Badge v-if="item.persona_switch" tone="warning" dot pulse>
            {{ t('groups.settings.role.waiting', { name: item.persona_switch.name }) }}
          </Badge>
        </div>
      </div>
      <IconButton
        v-if="switchable"
        :icon="ChevronsUpDown"
        :label="t('groups.pick')"
        variant="secondary"
        :tooltip="false"
        class="shrink-0 sm:hidden"
        @click="emit('switch')"
      />
    </div>
    <div class="flex flex-wrap items-center gap-2.5 max-sm:justify-between">
      <div class="flex flex-wrap items-center gap-2.5">
        <SegmentedControl
          v-model="mode"
          :options="modes"
          size="sm"
          :disabled="!accepting || chat.isPending.value || !opened"
          :label="t('overview.groups.chat', { name })"
        />
        <div class="inline-flex items-center gap-2">
          <label
            :for="openId"
            class="text-sm font-medium text-ink-2 select-none"
            :class="!accepting ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'"
          >
            {{ t('groups.open') }}
          </label>
          <Switch
            :id="openId"
            v-model="opened"
            :loading="open.isPending.value"
            :disabled="!accepting || open.isPending.value"
          />
        </div>
      </div>
      <DropdownMenu :items="actions">
        <IconButton :icon="Ellipsis" :label="t('groups.actions')" variant="secondary" />
      </DropdownMenu>
    </div>
    <QuietDialog v-model:open="quieting" :scene="scene" :time-zone="item.timezone" />
  </header>
</template>
