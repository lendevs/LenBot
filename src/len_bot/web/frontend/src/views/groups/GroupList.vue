<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, Search } from '@lucide/vue'
import type { HostScene } from '../../api/host'
import { sceneTitles } from '../../api/scenes'
import Avatar from '../../ui/Avatar.vue'
import IconButton from '../../ui/IconButton.vue'
import Input from '../../ui/Input.vue'
import StatusDot from '../../ui/StatusDot.vue'
import { groupLabel } from '../../layouts/shell/scenes'
import { statusTones, useStatusLabel } from './status'

const props = withDefaults(
  defineProps<{ scenes: HostScene[]; selected: string; surface?: 'page' | 'raised' }>(),
  { surface: 'page' },
)
const emit = defineEmits<{ select: [scene: string]; add: [] }>()

const { t } = useI18n()
const statusLabel = useStatusLabel()
const query = ref('')

const number = (scene: string) => scene.split(':').slice(2).join(':')
/** Telegram and Feishu groups name their platform; QQ groups are the default. */
const platform = (scene: string) => {
  const name = scene.split(':', 1)[0]
  return name === 'onebot' ? '' : t(`chatPlatforms.${name}`)
}
const titles = sceneTitles as Record<string, string>
const shown = computed(() => {
  const words = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return props.scenes
  return props.scenes.filter((item) => {
    const text = `${groupLabel(item.scene)} ${item.scene} ${item.persona.name}`.toLowerCase()
    return words.every((word) => text.includes(word))
  })
})
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
    <nav
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
          <strong class="truncate text-sm font-medium text-ink group-aria-[current=page]:font-semibold">
            {{ groupLabel(item.scene) }}
          </strong>
          <span class="truncate text-xs text-muted tabular">
            {{
              [
                item.chat_status.status !== 'chatting' ? t(`groups.status.${item.chat_status.status}`) : '',
                platform(item.scene),
                titles[item.scene] ? number(item.scene) : '',
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
