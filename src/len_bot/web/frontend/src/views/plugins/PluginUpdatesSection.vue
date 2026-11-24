<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ArrowUpCircle, Puzzle } from '@lucide/vue'
import { keys } from '../../api/query'
import { pluginsApi, type PluginUpdate } from '../../api/plugins'
import type { PluginUpdateResult } from '../../api/system'
import { readHostState, readPendingRestart, readPluginUpdates } from '../../api/hostStore'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

/** Installed plugins with a newer catalog version; shown only while there are some. */
withDefaults(defineProps<{ busy?: boolean }>(), { busy: false })

const { t } = useI18n()
const queryClient = useQueryClient()
const updates = useQuery({
  queryKey: keys.plugins.updates(),
  queryFn: ({ signal }) => pluginsApi.updates(signal),
})
const items = computed<PluginUpdate[]>(() => updates.data.value ?? [])
const ready = computed(() => items.value.filter((item) => item.compatible && !item.prepared))

const apply = useMutation({
  mutationFn: (names: string[] | null) => pluginsApi.applyUpdates(names),
  onSuccess: (snapshot) => {
    queryClient.setQueryData(keys.plugins.all(), snapshot)
    queryClient.setQueryData(keys.plugins.updates(), snapshot.updates)
    const results = (snapshot.operation?.updates ?? []) as PluginUpdateResult[]
    const failed = results.filter((item) => item.error)
    if (failed.length)
      toast.error(
        t('plugins.updates.failed', { names: failed.map((item) => item.name).join(t('personas.separator')) }),
        {
          detail: failed.map((item) => `${item.name}: ${item.error}`).join('\n'),
        },
      )
    else if (results.some((item) => item.restart_required)) toast.success(t('plugins.updates.restart'))
    else toast.success(t('plugins.updates.done', { n: results.length }, results.length))
    if (results.some((item) => item.restart_required)) void readPendingRestart()
  },
  onError: (error) =>
    toast.error(t('plugins.updates.failedAll'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
  onSettled: () => {
    void readHostState()
    void readPluginUpdates()
    void queryClient.invalidateQueries({ queryKey: keys.plugins.all() })
    void queryClient.invalidateQueries({ queryKey: ['plugin-catalog'] })
  },
})

const runningAll = computed(() => apply.isPending.value && apply.variables.value === null)
const runningOne = (name: string) =>
  apply.isPending.value && Array.isArray(apply.variables.value) && apply.variables.value.includes(name)
</script>

<template>
  <section
    v-if="items.length"
    class="flex min-w-0 animate-rise flex-col gap-3 rounded-xl border border-line-strong bg-fill px-4 py-3.5 sm:px-5 sm:py-4"
  >
    <header class="flex flex-wrap items-center justify-between gap-3">
      <h3 class="flex items-center gap-2 text-base font-semibold text-ink tabular">
        <Puzzle class="size-4 text-info" aria-hidden="true" />
        {{ t('plugins.updates.title', { n: items.length }, items.length) }}
      </h3>
      <Button
        v-if="ready.length"
        size="sm"
        variant="primary"
        :icon="ArrowUpCircle"
        :loading="runningAll"
        :disabled="busy || apply.isPending.value"
        @click="apply.mutate(null)"
      >
        {{ runningAll ? t('plugins.updates.updating') : t('plugins.updates.all') }}
      </Button>
    </header>
    <ul class="flex list-none flex-col divide-y divide-line">
      <li
        v-for="item in items"
        :key="item.name"
        class="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 text-sm"
      >
        <div class="flex min-w-0 flex-1 items-baseline gap-2">
          <RouterLink
            :to="{ name: 'host-plugins', query: { item: item.name, part: 'version' } }"
            :aria-label="t('plugins.updates.inspect', { name: item.title || item.name })"
            class="min-w-0 truncate rounded-xs font-medium text-ink transition-colors hover:text-primary hover:underline focus-visible:focus-ring"
          >
            {{ item.title || item.name }}
          </RouterLink>
          <span
            v-if="item.title && item.title !== item.name"
            class="hidden truncate font-mono text-xs text-subtle sm:inline"
          >
            {{ item.name }}
          </span>
        </div>
        <span class="text-muted tabular">
          v{{ item.installed_version }} →
          <strong class="font-semibold text-ink">v{{ item.version }}</strong>
        </span>
        <Badge v-if="item.prepared" tone="info">{{ t('plugins.updates.prepared') }}</Badge>
        <Badge v-else-if="!item.compatible" tone="warning" :title="item.incompatible_reason ?? undefined">
          {{ t('plugins.updates.incompatible') }}
        </Badge>
        <Button
          v-else
          size="sm"
          :loading="runningOne(item.name)"
          :disabled="busy || apply.isPending.value"
          @click="apply.mutate([item.name])"
        >
          {{ runningOne(item.name) ? t('plugins.updates.updating') : t('plugins.updates.one') }}
        </Button>
      </li>
    </ul>
  </section>
</template>
