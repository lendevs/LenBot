<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { ArrowRight, MessagesSquare, Plus, Search } from '@lucide/vue'
import { hostApi, type HostState } from '../../api/host'
import { host, readHostState } from '../../api/hostStore'
import { formatNumber } from '../../i18n/format'
import { groupLabel } from '../../layouts/shell/scenes'
import Avatar from '../../ui/Avatar.vue'
import Button from '../../ui/Button.vue'
import EmptyState from '../../ui/EmptyState.vue'
import Input from '../../ui/Input.vue'
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
  onError: (error) => toast.error(t('groups.chatFailed'), { detail: describeError(error, t('ui.error.network')).message }),
  onSettled: () => void readHostState(),
})
const switching = (scene: string) => chat.isPending.value && chat.variables.value?.scene === scene
</script>

<template>
  <section class="flex min-w-0 flex-col gap-3">
    <div class="flex items-center justify-between gap-2">
      <h2 class="text-base font-semibold">{{ t('overview.groups.title') }}</h2>
      <Button size="sm" variant="ghost" :icon-right="ArrowRight" :to="groupsTarget()">{{ t('overview.groups.manage') }}</Button>
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
          <RouterLink :to="groupsTarget(item.scene)" class="group flex min-w-0 flex-1 items-center gap-3 rounded-md focus-visible:focus-ring">
            <Avatar :name="groupLabel(item.scene)" shape="square" :size="32" />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-medium text-ink group-hover:underline" :class="!item.chat_enabled && 'text-muted'">
                {{ groupLabel(item.scene) }}
              </span>
              <span class="flex min-w-0 items-center gap-1.5 text-xs text-muted">
                <StatusDot :tone="statusTones[item.chat_status.status]" />
                <span class="truncate">
                  {{
                    [
                      statusLabel(item.chat_status, item.timezone),
                      members(item.scene) === undefined ? '' : t('groups.members', { n: formatNumber(members(item.scene)!) }),
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
            :model-value="switching(item.scene) ? Boolean(chat.variables.value?.enabled) : item.chat_enabled"
            :loading="switching(item.scene)"
            :disabled="!state.connection.accepting"
            :aria-label="t('overview.groups.chat', { name: groupLabel(item.scene) })"
            @update:model-value="(enabled: boolean) => chat.mutate({ scene: item.scene, enabled })"
          />
        </li>
        <li v-if="!shown.length" class="px-4 py-6 text-center text-sm text-muted">{{ t('common.noResults') }}</li>
      </ul>
    </template>
  </section>
</template>
