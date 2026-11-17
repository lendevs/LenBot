<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { ArrowRight, MessagesSquare, Plus, Search } from '@lucide/vue'
import { hostApi, type HostState, type WakeLevel } from '../../api/host'
import { host, readHostState } from '../../api/hostStore'
import { formatNumber } from '../../i18n/format'
import { groupLabel, groupSecondaryId } from '../../layouts/shell/scenes'
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
      <h2 class="flex items-center gap-2 text-base font-semibold text-ink">
        {{ t('overview.groups.title') }}
        <span v-if="state.scenes.length" class="text-xs font-normal text-muted tabular">
          {{ formatNumber(state.scenes.length) }}
        </span>
      </h2>
      <Button size="sm" variant="ghost" :icon-right="ArrowRight" :to="groupsTarget()">
        {{ t('overview.groups.manage') }}
      </Button>
    </div>
    <div v-if="!state.scenes.length" class="border-y border-line">
      <EmptyState :icon="MessagesSquare" :title="t('groups.empty')" compact>
        <Button variant="primary" size="sm" :icon="Plus" :to="groupsTarget()">{{ t('groups.add') }}</Button>
      </EmptyState>
    </div>
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
      <ul class="flex list-none flex-col divide-y divide-line border-y border-line">
        <li v-for="item in shown" :key="item.scene" class="flex min-w-0 flex-col gap-2.5 py-3">
          <div class="flex min-w-0 items-center gap-3">
            <RouterLink
              :to="groupsTarget(item.scene)"
              class="group link-plain flex min-w-0 flex-1 items-center gap-3 rounded-md focus-visible:focus-ring"
            >
              <Avatar :name="groupLabel(item.scene)" shape="square" :size="32" />
              <span class="min-w-0 flex-1">
                <span class="flex min-w-0 items-baseline gap-2">
                  <span
                    class="truncate text-sm font-medium transition-colors group-hover:text-primary"
                    :class="!item.chat_enabled || !isOpen(item) ? 'text-muted' : 'text-ink'"
                  >
                    {{ groupLabel(item.scene) }}
                  </span>
                  <span
                    v-if="groupSecondaryId(item.scene)"
                    class="shrink-0 font-mono text-xs text-subtle tabular"
                  >
                    {{ groupSecondaryId(item.scene) }}
                  </span>
                </span>
                <span class="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-muted tabular">
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
            <Switch
              :model-value="isOpen(item)"
              :loading="opening(item.scene)"
              :disabled="!state.connection.accepting"
              :aria-label="t('overview.groups.open', { name: groupLabel(item.scene) })"
              @update:model-value="(enabled: boolean) => open.mutate({ scene: item.scene, enabled })"
            />
          </div>
          <div class="flex min-w-0 flex-wrap items-center gap-2 pl-11">
            <SegmentedControl
              :model-value="levelOf(item)"
              :options="levels"
              size="sm"
              :disabled="level.isPending.value || !isOpen(item)"
              :label="t('overview.groups.level', { name: groupLabel(item.scene) })"
              @update:model-value="
                (value) => value && level.mutate({ scene: item.scene, value: value as WakeLevel })
              "
            />
            <button
              type="button"
              class="inline-flex h-8 shrink-0 cursor-pointer items-center justify-center rounded-md border px-2.5 text-xs font-medium transition-colors focus-visible:focus-ring disabled:cursor-not-allowed disabled:opacity-50 pointer-coarse:h-10"
              :class="
                chatOn(item)
                  ? 'border-line-strong bg-surface-raised text-ink shadow-card hover:bg-hover'
                  : 'border-line bg-fill text-muted hover:bg-hover hover:text-ink'
              "
              :aria-pressed="chatOn(item)"
              :disabled="!state.connection.accepting || switching(item.scene) || !isOpen(item)"
              :title="t(chatOn(item) ? 'overview.groups.chatHint' : 'overview.groups.pluginsHint')"
              :aria-label="t('overview.groups.chat', { name: groupLabel(item.scene) })"
              @click="chat.mutate({ scene: item.scene, enabled: !item.chat_enabled })"
            >
              {{ t(chatOn(item) ? 'overview.groups.modeChat' : 'overview.groups.modePlugins') }}
            </button>
          </div>
        </li>
        <li v-if="!shown.length" class="py-6 text-center text-sm text-muted">
          {{ t('common.noResults') }}
        </li>
      </ul>
    </template>
  </section>
</template>
