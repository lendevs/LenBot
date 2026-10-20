<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { CircleAlert, MessagesSquare, Wrench } from '@lucide/vue'
import type { PluginsSnapshot } from '../../api/plugins'
import Avatar from '../../ui/Avatar.vue'
import Badge from '../../ui/Badge.vue'
import { usePluginsState } from './state'
import {
  descriptionOf,
  enabledIn,
  featureCount,
  isolationOf,
  permissionsOf,
  runningOf,
  scenesUsing,
  statusOf,
  statusTone,
  versionOf,
} from './view'

const props = defineProps<{ name: string; snapshot: PluginsSnapshot }>()
const emit = defineEmits<{ open: [] }>()

const { t } = useI18n()
const state = usePluginsState()
const health = computed(() => state.healthOf(props.name))
const status = computed(() => statusOf(props.snapshot, props.name, health.value))
const running = computed(() => runningOf(props.snapshot, props.name))
const on = computed(() => enabledIn(props.snapshot, props.name))
const groups = computed(() => scenesUsing(props.snapshot, props.name).length)
const features = computed(() => featureCount(running.value))
const permissions = computed(() => permissionsOf(props.snapshot, props.name))
const recent = computed(() => health.value?.errors_last_hour ?? 0)
</script>

<template>
  <article
    class="relative flex flex-col gap-3 rounded-lg border border-line bg-surface p-4 shadow-card transition-[border-color,box-shadow] duration-150 hover:border-line-strong hover:shadow-hover"
  >
    <div class="flex items-center gap-3">
      <span class="flex" :class="!on && 'opacity-60 grayscale'" aria-hidden="true">
        <Avatar :name="name" shape="square" :size="40" />
      </span>
      <div class="min-w-0 flex-1">
        <!-- The stretched button makes the whole card open the plugin. -->
        <button
          type="button"
          class="block max-w-full cursor-pointer truncate text-left text-base font-semibold after:absolute after:inset-0 after:rounded-lg focus-visible:outline-none focus-visible:after:focus-ring"
          :class="on ? 'text-ink' : 'text-ink-2'"
          @click="emit('open')"
        >
          {{ name }}
        </button>
        <p v-if="versionOf(snapshot, name)" class="truncate text-xs text-subtle tabular">v{{ versionOf(snapshot, name) }}</p>
      </div>
      <Badge :tone="statusTone(status)" dot>{{ t(`plugins.status.${status}`) }}</Badge>
    </div>
    <p class="line-clamp-2 min-h-10 text-sm text-muted">{{ descriptionOf(snapshot, name) }}</p>
    <div class="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-line pt-3 text-xs text-muted">
      <span class="inline-flex items-center gap-1">
        <MessagesSquare :size="14" aria-hidden="true" />
        {{ groups ? t('plugins.card.groups', { n: groups }, groups) : t('plugins.card.noGroups') }}
      </span>
      <span v-if="features" class="inline-flex items-center gap-1">
        <Wrench :size="14" aria-hidden="true" />{{ t('plugins.card.features', { n: features }, features) }}
      </span>
      <span v-if="recent" class="inline-flex items-center gap-1 text-error">
        <CircleAlert :size="14" aria-hidden="true" />{{ t('plugins.card.errors', { n: recent }, recent) }}
      </span>
      <Badge v-if="isolationOf(snapshot, name) === 'process'">{{ t('plugins.isolation.processShort') }}</Badge>
      <Badge v-if="permissions === null" tone="warning">{{ t('plugins.permissions.undeclaredShort') }}</Badge>
    </div>
  </article>
</template>
