<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { ArrowRight, MessagesSquare, Plus, Search } from '@lucide/vue'
import { hostApi, type HostState, type WakeLevel } from '../../api/host'
import { host, readHostState } from '../../api/hostStore'
import { formatNumber } from '../../i18n/format'
import { groupLabel } from '../../layouts/shell/scenes'
import Avatar from '../../ui/Avatar.vue'
import Button from '../../ui/Button.vue'
import EmptyState from '../../ui/EmptyState.vue'
import Input from '../../ui/Input.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import StatusDot from '../../ui/StatusDot.vue'
import Switch from '../../ui/Switch.vue'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'
import { groupsTarget } from '../groups/route'
import { statusTones, useStatusLabel } from '../groups/status'

const { t } = useI18n()
const statusLabel = useStatusLabel()
const state = computed(() => host.state as HostState)
const query = ref('')
const shown = computed(() => {
  const words = query.value.trim().toLowerCase()
  return state.value.scenes.filter(
    (item) => !words || groupLabel(item.scene).toLowerCase().includes(words) || item.scene.includes(words),
  )
})
const members = (scene: string) => (host.members as Record<string, number>)[scene]

const chat = useMutation({
  mutationFn: ({ scene, enabled }: { scene: string; enabled: boolean }) => hostApi.setChat(scene, enabled),
  onSuccess: (_, { scene, enabled }) =>
    toast.success(t(enabled ? 'groups.chatOn' : 'groups.chatOff', { name: groupLabel(scene) })),
  onError: (error) =>
    toast.error(t('groups.chatFailed'), { detail: describeError(error, t('ui.error.network')).message }),
  onSettled: () => void readHostState(),
})
const open = useMutation({
  mutationFn: ({ scene, enabled }: { scene: string; enabled: boolean }) => hostApi.setOpen(scene, enabled),
  onSuccess: (_, { scene, enabled }) =>
    toast.success(t(enabled ? 'groups.opened' : 'groups.closed', { name: groupLabel(scene) })),
  onError: (error) =>
    toast.error(t('groups.openFailed'), { detail: describeError(error, t('ui.error.network')).message }),
  onSettled: () => void readHostState(),
})
const opening = (scene: string) => open.isPending.value && open.variables.value?.scene === scene
const isOpen = (item: HostState['scenes'][number]) =>
  opening(item.scene) ? Boolean(open.variables.value?.enabled) : item.scene_open
const switching = (scene: string) => chat.isPending.value && chat.variables.value?.scene === scene
const chatOn = (item: HostState['scenes'][number]) =>
  switching(item.scene) ? Boolean(chat.variables.value?.enabled) : item.chat_enabled

const levels = computed(() =>
  (['active', 'moderate', 'quiet'] as const).map((value) => ({
    value,
    label: t(`overview.groups.levels.${value}`),
  })),
)
const level = useMutation({
  mutationFn: ({ scene, value }: { scene: string; value: WakeLevel }) => hostApi.setWakeLevel(scene, value),
  onError: (error) =>
    toast.error(t('overview.groups.levelFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
  onSettled: () => void readHostState(),
})
const levelOf = (item: HostState['scenes'][number]): WakeLevel | '' =>
  level.isPending.value && level.variables.value?.scene === item.scene
    ? level.variables.value.value
    : (item.wake_level ?? '')
</script>

<template>
  <section class="flex min-w-0 flex-col gap-3">
    <div class="flex items-center justify-between gap-2">
      <h2 class="text-base font-semibold">{{ t('overview.groups.title') }}</h2>
      <Button size="sm" variant="ghost" :icon-right="ArrowRight" :to="groupsTarget()">
        {{ t('overview.groups.manage') }}
      </Button>
    </div>
    <EmptyState v-if="!state.scenes.length" :icon="MessagesSquare" :title="t('groups.empty')" compact>
      <Button variant="primary" size="sm" :icon="Plus" :to="groupsTarget()">{{ t('groups.add') }}</Button>
    </EmptyState>
    <template v-else>
      <Input
        v-if="state.scenes.length > 4"
        v-model="query"
        type="search"
        size="sm"
        :icon="Search"
        clearable
        :placeholder="t('groups.search')"
        :aria-label="t('groups.search')"
      />
      <ul class="flex flex-col divide-y divide-line rounded-lg border border-line bg-surface">
        <li v-for="item in shown" :key="item.scene" class="flex min-w-0 items-center gap-3 px-4 py-2.5">
          <RouterLink
            :to="groupsTarget(item.scene)"
            class="group flex min-w-0 flex-1 items-center gap-3 rounded-md focus-visible:focus-ring"
          >
            <Avatar :name="groupLabel(item.scene)" shape="square" :size="32" />
            <span class="min-w-0 flex-1">
              <span
                class="block truncate text-sm font-medium text-ink group-hover:underline"
                :class="(!item.chat_enabled || !isOpen(item)) && 'text-muted'"
              >
                {{ groupLabel(item.scene) }}
              </span>
              <span class="flex min-w-0 items-center gap-1.5 text-xs text-muted">
                <StatusDot :tone="statusTones[item.chat_status.status]" />
                <span class="truncate">
                  {{
                    [
                      statusLabel(item.chat_status, item.timezone),
                      members(item.scene) === undefined
                        ? ''
                        : t('groups.members', { n: formatNumber(members(item.scene)!) }),
                      item.persona.name,
                    ]
                      .filter(Boolean)
                      .join(' · ')
                  }}
                </span>
              </span>
            </span>
          </RouterLink>
          <SegmentedControl
            :model-value="levelOf(item)"
            :options="levels"
            size="sm"
            class="max-sm:hidden"
            :disabled="level.isPending.value || !isOpen(item)"
            :label="t('overview.groups.level', { name: groupLabel(item.scene) })"
            @update:model-value="
              (value) => value && level.mutate({ scene: item.scene, value: value as WakeLevel })
            "
          />
          <button
            type="button"
            class="inline-flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-lg border text-sm font-semibold transition-colors focus-visible:focus-ring disabled:cursor-not-allowed disabled:opacity-50"
            :class="
              chatOn(item)
                ? 'border-primary bg-primary text-on-primary hover:brightness-95'
                : 'border-line-strong bg-fill text-ink-2 hover:bg-hover'
            "
            :aria-pressed="chatOn(item)"
            :disabled="!state.connection.accepting || switching(item.scene) || !isOpen(item)"
            :title="t(chatOn(item) ? 'overview.groups.chatHint' : 'overview.groups.pluginsHint')"
            :aria-label="t('overview.groups.chat', { name: groupLabel(item.scene) })"
            @click="chat.mutate({ scene: item.scene, enabled: !item.chat_enabled })"
          >
            {{ t(chatOn(item) ? 'overview.groups.modeChat' : 'overview.groups.modePlugins') }}
          </button>
          <Switch
            :model-value="isOpen(item)"
            :loading="opening(item.scene)"
            :disabled="!state.connection.accepting"
            :aria-label="t('overview.groups.open', { name: groupLabel(item.scene) })"
            @update:model-value="(enabled: boolean) => open.mutate({ scene: item.scene, enabled })"
          />
        </li>
        <li v-if="!shown.length" class="px-4 py-6 text-center text-sm text-muted">
          {{ t('common.noResults') }}
        </li>
      </ul>
    </template>
  </section>
</template>
