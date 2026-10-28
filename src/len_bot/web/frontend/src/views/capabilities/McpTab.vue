<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'
import { useMediaQuery } from '@vueuse/core'
import { Plus, Server } from '@lucide/vue'
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
/** The open service; null is adding one, undefined is none. */
const selected = computed<string | null | undefined>(() => {
  if (item.value === NEW) return null
  if (item.value && names.value.includes(item.value)) return item.value
  return wide.value ? names.value[0] : undefined
})
const select = (value: string | null | undefined) =>
  void router.replace({ query: { ...route.query, item: value === null ? NEW : (value ?? undefined) } })
watch(
  () => [item.value, names.value.length],
  () => {
    if (state.value && item.value && item.value !== NEW && !names.value.includes(item.value))
      select(undefined)
  },
)
const subtitle = (name: string) => {
  const value = running(name)
  if (!value) return t('capabilities.mcp.pending')
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
  <div v-else-if="state" class="grid min-w-0 gap-5 lg:grid-cols-[18rem_minmax(0,1fr)]">
    <section v-if="wide || selected === undefined" class="flex min-w-0 flex-col gap-3">
      <div class="flex items-center justify-between gap-2">
        <h2 class="text-base font-semibold">{{ t('capabilities.mcp.title') }}</h2>
        <Button size="sm" :icon="Plus" @click="select(null)">{{ t('capabilities.mcp.add') }}</Button>
      </div>
      <ul class="flex list-none flex-col gap-1">
        <li v-for="name in names" :key="name">
          <button
            type="button"
            class="flex w-full min-w-0 cursor-pointer flex-col gap-1 rounded-md px-3 py-2 text-left transition-colors hover:bg-hover focus-visible:focus-ring"
            :class="selected === name && 'bg-selected'"
            :aria-current="selected === name || undefined"
            @click="select(name)"
          >
            <span class="flex min-w-0 items-center gap-2">
              <span class="min-w-0 flex-1 truncate font-mono text-sm font-medium text-ink">{{ name }}</span>
              <Badge v-if="running(name)" :tone="mcpTone(running(name)!.status)" dot>
                {{ t(`capabilities.mcp.status.${running(name)!.status}`, running(name)!.status) }}
              </Badge>
              <Badge v-else tone="warning" dot>{{ t('capabilities.mcp.pendingShort') }}</Badge>
            </span>
            <span class="truncate text-xs text-muted">{{ subtitle(name) }}</span>
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
    />
  </div>
</template>
