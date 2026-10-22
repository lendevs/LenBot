<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  ArrowUpRight,
  Check,
  ChevronDown,
  Ellipsis,
  FlaskConical,
  Moon,
  RefreshCcw,
  Sun,
  UserRound,
} from '@lucide/vue'
import { hostApi, type HostScene } from '../../api/host'
import { keys } from '../../api/query'
import { sceneTitles } from '../../api/scenes'
import { host, readHostState } from '../../api/hostStore'
import { formatNumber } from '../../i18n/format'
import { groupLabel } from '../../layouts/shell/scenes'
import { useHostEvent } from '../../realtime/stream'
import Avatar from '../../ui/Avatar.vue'
import Badge from '../../ui/Badge.vue'
import DropdownMenu, { type MenuEntry } from '../../ui/DropdownMenu.vue'
import IconButton from '../../ui/IconButton.vue'
import StatusDot from '../../ui/StatusDot.vue'
import Switch from '../../ui/Switch.vue'
import { confirm } from '../../ui/confirm'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'
import QuietDialog from './QuietDialog.vue'
import { roleLabel, useRoleSwitch, useRoles } from './roleSwitch'
import { useSessionActions } from './session/useSessionActions'
import { statusTones, useStatusLabel } from './status'

const props = defineProps<{ item: HostScene }>()

const { t } = useI18n()
const router = useRouter()
const client = useQueryClient()
const statusLabel = useStatusLabel()
const quieting = ref(false)

const scene = computed(() => props.item.scene)
const name = computed(() => groupLabel(scene.value))
const members = computed(() => (host.members as Record<string, number>)[scene.value])
const details = computed(() =>
  [
    (sceneTitles as Record<string, string>)[scene.value] ? scene.value.split(':').slice(2).join(':') : '',
    members.value === undefined ? '' : t('groups.members', { n: formatNumber(members.value) }),
  ].filter(Boolean),
)

const control = useQuery({
  queryKey: computed(() => keys.scene.control(scene.value)),
  queryFn: ({ signal }) => hostApi.control(scene.value, signal),
})
useHostEvent('host.state', (event) => {
  if (event.scene === null || event.scene === scene.value)
    void client.invalidateQueries({ queryKey: keys.scene.control(scene.value) })
})
const temporaryQuiet = computed(() => {
  const quiet = control.data.value?.temporary_quiet
  return quiet && quiet.until * 1000 > Date.now() ? quiet : null
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
const enabled = computed({
  get: () => (chat.isPending.value ? Boolean(chat.variables.value) : props.item.chat_enabled),
  set: (value: boolean) => chat.mutate(value),
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
  const confirmed = await confirm({
    title: t('groups.settings.role.title', { group: name.value, name: roleLabel(role) }),
    confirmLabel: t('groups.settings.role.action'),
    tone: 'primary',
  })
  if (confirmed) switchRole(scene.value, role)
}

const actions = computed<MenuEntry[]>(() => [
  temporaryQuiet.value
    ? {
        label: t('groups.quiet.resume'),
        icon: Sun,
        disabled: resume.isPending.value,
        select: () => resume.mutate(),
      }
    : { label: t('groups.quiet.action'), icon: Moon, select: () => (quieting.value = true) },
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
  <header class="flex flex-wrap items-center gap-x-4 gap-y-3">
    <span class="flex max-sm:hidden" aria-hidden="true">
      <Avatar :name="name" shape="square" :size="44" />
    </span>
    <div class="min-w-0 flex-1">
      <h1 class="truncate text-xl font-semibold">{{ name }}</h1>
      <p class="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
        <span class="inline-flex items-center gap-1.5">
          <StatusDot :tone="statusTones[item.chat_status.status]" />
          {{ statusLabel(item.chat_status, item.timezone) }}
        </span>
        <span v-for="detail in details" :key="detail" class="tabular">{{ detail }}</span>
        <DropdownMenu :items="roleItems" align="start">
          <button
            type="button"
            class="-mx-1 inline-flex min-w-0 cursor-pointer items-center gap-1 rounded-md px-1 transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring"
            :aria-label="t('groups.role.label', { name: item.persona.name })"
          >
            <UserRound :size="14" aria-hidden="true" />
            <span class="truncate">{{ item.persona.name }}</span>
            <ChevronDown :size="13" aria-hidden="true" />
          </button>
        </DropdownMenu>
        <Badge v-if="item.persona_switch" tone="warning" dot pulse>
          {{ t('groups.settings.role.waiting', { name: item.persona_switch.name }) }}
        </Badge>
      </p>
    </div>
    <div class="flex items-center gap-2">
      <label class="inline-flex cursor-pointer items-center gap-2.5 text-sm font-medium text-ink-2">
        {{ t('groups.chat') }}
        <Switch v-model="enabled" :loading="chat.isPending.value" />
      </label>
      <DropdownMenu :items="actions">
        <IconButton :icon="Ellipsis" :label="t('groups.actions')" variant="secondary" />
      </DropdownMenu>
    </div>
    <QuietDialog v-model:open="quieting" :scene="scene" :time-zone="item.timezone" />
  </header>
</template>
