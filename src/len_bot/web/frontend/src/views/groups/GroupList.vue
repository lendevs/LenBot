<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, Search } from '@lucide/vue'
import type { ChatStatus, HostScene } from '../../api/host'
import Avatar from '../../ui/Avatar.vue'
import Badge from '../../ui/Badge.vue'
import IconButton from '../../ui/IconButton.vue'
import Input from '../../ui/Input.vue'
import StatusDot from '../../ui/StatusDot.vue'
import { groupLabel, groupSecondaryId, isPrivateScene, scenePlatform } from '../../layouts/shell/scenes'
import { statusTones, useStatusLabel } from './status'

const props = withDefaults(
  defineProps<{ scenes: HostScene[]; selected: string; surface?: 'page' | 'raised' }>(),
  { surface: 'page' },
)
const emit = defineEmits<{ select: [scene: string]; add: [] }>()

const { t, te } = useI18n()
const statusLabel = useStatusLabel()
const query = ref('')
const navEl = ref<HTMLElement>()

const abnormalStatuses = ['quiet', 'limited', 'paused', 'closed'] as const
type AbnormalStatus = (typeof abnormalStatuses)[number]
type StatusFilter = 'all' | AbnormalStatus
const statusFilter = ref<StatusFilter>('all')

const statusCounts = computed(() => {
  const counts: Record<ChatStatus['status'], number> = {
    chatting: 0,
    paused: 0,
    quiet: 0,
    limited: 0,
    closed: 0,
  }
  for (const item of props.scenes) counts[item.chat_status.status] += 1
  return counts
})
const presentAbnormal = computed(() => abnormalStatuses.filter((status) => statusCounts.value[status] > 0))
watch(presentAbnormal, (statuses) => {
  if (statusFilter.value !== 'all' && !statuses.includes(statusFilter.value)) {
    statusFilter.value = 'all'
  }
})

const localizedPlatform = (scene: string) => {
  const name = scenePlatform(scene)
  return name && te(`chatPlatforms.${name}`) ? t(`chatPlatforms.${name}`) : name
}
/** Telegram and Feishu groups name their platform; QQ groups are the default. */
const displayPlatform = (scene: string) => {
  const name = scenePlatform(scene)
  return !name || name === 'onebot' ? '' : localizedPlatform(scene)
}

const shown = computed(() => {
  const words = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  return props.scenes.filter((item) => {
    if (statusFilter.value !== 'all' && item.chat_status.status !== statusFilter.value) return false
    if (!words.length) return true
    const text = [
      groupLabel(item.scene),
      item.scene,
      item.persona.name,
      localizedPlatform(item.scene),
      t(`groups.status.${item.chat_status.status}`),
      isPrivateScene(item.scene) ? t('groups.join.kinds.private') : '',
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return words.every((word) => text.includes(word))
  })
})

function revealSelected() {
  void nextTick(() => {
    navEl.value?.querySelector<HTMLElement>('[aria-current="page"]')?.scrollIntoView({ block: 'nearest' })
  })
}
onMounted(revealSelected)
watch(() => props.selected, revealSelected)
</script>

<template>
  <div class="flex min-h-0 flex-col gap-2.5">
    <div class="flex items-center gap-1.5">
      <div class="min-w-0 flex-1">
        <Input
          v-model="query"
          type="search"
          size="sm"
          :icon="Search"
          :placeholder="t('groups.search')"
          :aria-label="t('groups.search')"
          clearable
        />
      </div>
      <IconButton :icon="Plus" :label="t('groups.add')" variant="secondary" @click="emit('add')" />
    </div>
    <div
      v-if="presentAbnormal.length"
      class="flex flex-wrap items-center gap-1"
      role="group"
      :aria-label="t('groups.list')"
    >
      <button
        type="button"
        class="inline-flex h-6 cursor-pointer items-center gap-1 rounded-full px-2 text-xs font-medium transition-colors focus-visible:focus-ring pointer-coarse:h-8"
        :class="
          statusFilter === 'all' ? 'bg-selected text-ink' : 'bg-fill text-muted hover:bg-hover hover:text-ink'
        "
        :aria-pressed="statusFilter === 'all'"
        @click="statusFilter = 'all'"
      >
        <span>{{ t('groups.live.filters.all') }}</span>
        <span class="tabular opacity-75">{{ scenes.length }}</span>
      </button>
      <button
        v-for="status in presentAbnormal"
        :key="status"
        type="button"
        class="inline-flex h-6 cursor-pointer items-center gap-1.5 rounded-full px-2 text-xs font-medium transition-colors focus-visible:focus-ring pointer-coarse:h-8"
        :class="
          statusFilter === status
            ? 'bg-selected text-ink'
            : 'bg-fill text-muted hover:bg-hover hover:text-ink'
        "
        :aria-pressed="statusFilter === status"
        @click="statusFilter = statusFilter === status ? 'all' : status"
      >
        <StatusDot :tone="statusTones[status]" />
        <span>{{ t(`groups.status.${status}`) }}</span>
        <span class="tabular opacity-75">{{ statusCounts[status] }}</span>
      </button>
    </div>
    <nav
      ref="navEl"
      :aria-label="t('groups.list')"
      class="-mx-1 flex min-h-0 flex-col gap-0.5 overflow-y-auto px-1 scrollbar-thin"
    >
      <button
        v-for="item in shown"
        :key="item.scene"
        type="button"
        class="group flex w-full cursor-pointer items-center gap-3 rounded-md px-2.5 py-2 text-left transition-colors duration-150 hover:bg-hover focus-visible:focus-ring aria-[current=page]:bg-selected"
        :aria-current="item.scene === selected ? 'page' : undefined"
        @click="emit('select', item.scene)"
      >
        <span class="relative shrink-0">
          <span class="flex" aria-hidden="true">
            <Avatar :name="groupLabel(item.scene)" shape="square" :size="36" />
          </span>
          <span
            class="absolute -right-0.5 -bottom-0.5 flex rounded-full p-0.5 transition-colors duration-150 group-hover:bg-hover group-aria-[current=page]:bg-selected"
            :class="surface === 'raised' ? 'bg-surface-raised' : 'bg-page'"
          >
            <StatusDot
              :tone="statusTones[item.chat_status.status]"
              :label="statusLabel(item.chat_status, item.timezone)"
            />
          </span>
        </span>
        <span class="grid min-w-0 flex-1 gap-0.5 leading-snug">
          <span class="flex min-w-0 items-center gap-1.5">
            <strong class="truncate text-sm font-medium text-ink group-aria-[current=page]:font-semibold">
              {{ groupLabel(item.scene) }}
            </strong>
            <Badge v-if="isPrivateScene(item.scene)" size="sm">
              {{ t('groups.join.kinds.private') }}
            </Badge>
          </span>
          <span class="truncate text-xs text-muted tabular">
            {{
              [
                item.chat_status.status !== 'chatting' ? t(`groups.status.${item.chat_status.status}`) : '',
                displayPlatform(item.scene),
                groupSecondaryId(item.scene),
                item.persona.name,
              ]
                .filter(Boolean)
                .join(' · ')
            }}
          </span>
        </span>
      </button>
      <p v-if="scenes.length && !shown.length" class="px-2 py-6 text-center text-sm text-muted">
        {{ t('common.noResults') }}
      </p>
    </nav>
  </div>
</template>
