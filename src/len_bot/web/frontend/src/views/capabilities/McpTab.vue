<script setup lang="ts">
import { computed, onActivated, onDeactivated, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'
import { useMediaQuery } from '@vueuse/core'
import { ChevronRight, Plus, Server } from '@lucide/vue'
import { capabilitiesApi } from '../../api/capabilities'
import { keys } from '../../api/query'
import { groupLabel } from '../../layouts/shell/scenes'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import EmptyState from '../../ui/EmptyState.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Skeleton from '../../ui/Skeleton.vue'
import McpEditor from './McpEditor.vue'
import { mcpTone } from './status'

const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const wide = useMediaQuery('(min-width: 1024px)')
const mcp = useQuery({ queryKey: keys.host.mcp(), queryFn: ({ signal }) => capabilitiesApi.mcp(signal) })
const state = computed(() => mcp.data.value)

const NEW = '+'
const names = computed(() =>
  state.value
    ? [
        ...new Set([...Object.keys(state.value.saved), ...state.value.running.map((item) => item.name)]),
      ].sort()
    : [],
)
const running = (name: string) => state.value?.running.find((item) => item.name === name)
const item = computed(() => (typeof route.query.item === 'string' ? route.query.item : null))
const active = ref(true)
const editorDirty = ref(false)
const frozenSelection = ref<string | null | undefined>(undefined)
/** The open service; null is adding one, undefined is none. */
const selected = computed<string | null | undefined>(() => {
  if (!active.value) return frozenSelection.value
  if (item.value === NEW) return null
  if (item.value && names.value.includes(item.value)) return item.value
  return wide.value ? names.value[0] : undefined
})
const select = (value: string | null | undefined) =>
  void router.replace({
    query: { ...route.query, tab: 'mcp', item: value === null ? NEW : (value ?? undefined) },
  })

onDeactivated(() => {
  frozenSelection.value = selected.value
  active.value = false
})
onActivated(() => {
  if (editorDirty.value && frozenSelection.value !== undefined) {
    const target = frozenSelection.value === null ? NEW : frozenSelection.value
    if (route.query.item !== target) {
      void router.replace({ query: { ...route.query, tab: 'mcp', item: target } }).finally(() => {
        active.value = true
      })
      return
    }
  }
  active.value = true
})
watch(
  () => selected.value !== undefined && editorDirty.value,
  (value) => emit('dirty', value),
  { immediate: true },
)
watch(
  () => [item.value, names.value.length],
  () => {
    if (!active.value) return
    if (state.value && item.value && item.value !== NEW && !names.value.includes(item.value))
      select(undefined)
  },
)
const subtitle = (name: string) => {
  const value = running(name)
  if (!value) return ''
  return [
    t('capabilities.mcp.tools', { n: value.tools.length }, value.tools.length),
    value.scenes.map(groupLabel).join(t('personas.separator')) || t('capabilities.mcp.noGroups'),
  ].join(' · ')
}
</script>

<template>
  <Skeleton v-if="mcp.isPending.value" :lines="6" />
  <ErrorNote
    v-else-if="mcp.isError.value"
    :title="t('capabilities.mcp.readFailed')"
    :error="mcp.error.value"
    :retry="mcp.refetch"
  />
  <EmptyState
    v-else-if="state && !names.length && selected === undefined"
    :icon="Server"
    :title="t('capabilities.mcp.empty')"
  >
    <Button variant="primary" :icon="Plus" @click="select(null)">{{ t('capabilities.mcp.add') }}</Button>
  </EmptyState>
  <div v-else-if="state" class="grid min-w-0 gap-6 lg:grid-cols-[17.5rem_minmax(0,1fr)] lg:gap-8">
    <section
      v-if="wide || selected === undefined"
      class="flex min-w-0 flex-col gap-3 lg:border-r lg:border-line lg:pr-6"
    >
      <div class="flex min-h-8 items-center justify-between gap-2">
        <h2 class="text-base font-semibold text-ink">{{ t('capabilities.mcp.title') }}</h2>
        <Button size="sm" :icon="Plus" @click="select(null)">{{ t('capabilities.mcp.add') }}</Button>
      </div>
      <ul class="flex list-none flex-col gap-1">
        <li v-for="name in names" :key="name">
          <button
            type="button"
            class="flex w-full min-w-0 cursor-pointer items-center gap-2 rounded-lg px-3 py-2.5 text-left transition-colors focus-visible:focus-ring"
            :class="selected === name ? 'bg-selected' : 'hover:bg-hover'"
            :aria-current="selected === name || undefined"
            @click="select(name)"
          >
            <span class="flex min-w-0 flex-1 flex-col gap-1">
              <span class="flex min-w-0 items-center gap-2">
                <span class="min-w-0 flex-1 truncate font-mono text-sm font-medium text-ink">{{ name }}</span>
                <Badge v-if="running(name)" :tone="mcpTone(running(name)!.status)" dot>
                  {{ t(`capabilities.mcp.status.${running(name)!.status}`, running(name)!.status) }}
                </Badge>
              </span>
              <span v-if="subtitle(name)" class="truncate text-xs text-muted tabular">
                {{ subtitle(name) }}
              </span>
            </span>
            <ChevronRight v-if="!wide" :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
          </button>
        </li>
      </ul>
    </section>
    <McpEditor
      v-if="selected !== undefined"
      :key="selected ?? NEW"
      :name="selected"
      :state="state"
      :wide="wide"
      @back="select(undefined)"
      @saved="(name) => select(name)"
      @removed="select(undefined)"
      @dirty="(value) => (editorDirty = value)"
    />
  </div>
</template>
