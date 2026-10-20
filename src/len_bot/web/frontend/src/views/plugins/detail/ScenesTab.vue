<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessagesSquare } from '@lucide/vue'
import { pluginsApi, type PluginsSnapshot } from '../../../api/plugins'
import { groupLabel } from '../../../layouts/shell/scenes'
import Avatar from '../../../ui/Avatar.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import Switch from '../../../ui/Switch.vue'
import { usePluginsState } from '../state'
import { enabledIn, scenesUsing } from '../view'

const props = defineProps<{ name: string; snapshot: PluginsSnapshot }>()

const { t } = useI18n()
const state = usePluginsState()
const scenes = computed(() => Object.keys(props.snapshot.scenes))
const used = computed(() => scenesUsing(props.snapshot, props.name))
const enabled = computed(() => enabledIn(props.snapshot, props.name))

function toggle(scene: string, on: boolean) {
  const current = props.snapshot.scenes[scene].saved ?? []
  const next = on ? [...current.filter((item) => item !== props.name), props.name] : current.filter((item) => item !== props.name)
  void state.run(`scene:${scene}`, () => pluginsApi.putScene(scene, next), { success: t('common.saved') })
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-3">
    <EmptyState v-if="!enabled" :icon="MessagesSquare" :title="t('plugins.scenes.enableFirst')" compact />
    <EmptyState v-else-if="!scenes.length" :icon="MessagesSquare" :title="t('plugins.scenes.none')" compact />
    <template v-else>
      <p class="text-sm text-muted tabular">{{ t('plugins.scenes.count', { n: used.length, total: scenes.length }) }}</p>
      <ul class="flex list-none flex-col divide-y divide-line rounded-xl border border-line bg-surface px-4">
        <li v-for="scene in scenes" :key="scene" class="flex items-center gap-3 py-2.5">
          <Avatar :name="groupLabel(scene)" shape="square" :size="32" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-medium text-ink">{{ groupLabel(scene) }}</p>
            <p class="truncate font-mono text-xs text-subtle">{{ scene.split(':').slice(2).join(':') || scene }}</p>
          </div>
          <Switch
            :model-value="used.includes(scene)"
            :loading="state.busy.value === `scene:${scene}`"
            :disabled="(state.busy.value !== null && state.busy.value !== `scene:${scene}`) || snapshot.scenes[scene].saved === null"
            :aria-label="t('plugins.scenes.useIn', { name: groupLabel(scene) })"
            @update:model-value="(value: boolean) => toggle(scene, value)"
          />
        </li>
      </ul>
    </template>
  </div>
</template>
