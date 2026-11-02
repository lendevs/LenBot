<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ArrowUpCircle, Puzzle } from '@lucide/vue'
import { keys } from '../../api/query'
import { pluginsApi, type PluginUpdate } from '../../api/plugins'
import type { PluginUpdateResult } from '../../api/system'
import { readPendingRestart, readPluginUpdates } from '../../api/hostStore'
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
    const results = (snapshot.operation?.updates ?? []) as PluginUpdateResult[]
    const failed = results.filter((item) => item.error)
    if (failed.length)
      toast.error(t('plugins.updates.failed', { names: failed.map((item) => item.name).join('、') }), {
        detail: failed.map((item) => `${item.name}: ${item.error}`).join('\n'),
      })
    else if (results.some((item) => item.restart_required)) toast.success(t('plugins.updates.restart'))
    else toast.success(t('plugins.updates.done', { n: results.length }, results.length))
    if (results.some((item) => item.restart_required)) void readPendingRestart()
  },
  onError: (error) =>
    toast.error(t('plugins.updates.failedAll'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
  onSettled: () => {
    void readPluginUpdates()
    void queryClient.invalidateQueries({ queryKey: keys.plugins.all() })
    void queryClient.invalidateQueries({ queryKey: ['plugin-catalog'] })
  },
})
const running = (name: string) => apply.isPending.value && Boolean(apply.variables.value?.includes(name))
</script>

<template>
  <section
    v-if="items.length"
    class="flex min-w-0 animate-rise flex-col gap-3 rounded-xl border border-brand/40 bg-brand-soft p-4 sm:p-5"
  >
    <header class="flex flex-wrap items-center justify-between gap-3">
      <h3 class="flex items-center gap-2 text-base font-semibold text-ink">
        <Puzzle class="size-4 text-primary" aria-hidden="true" />
        {{ t('plugins.updates.title', { n: items.length }, items.length) }}
      </h3>
      <Button
        v-if="ready.length"
        size="sm"
        variant="primary"
        :icon="ArrowUpCircle"
        :loading="apply.isPending.value && apply.variables.value === null"
        :disabled="busy || apply.isPending.value"
        @click="apply.mutate(null)"
      >
        {{ t('plugins.updates.all') }}
      </Button>
    </header>
    <ul class="flex list-none flex-col divide-y divide-brand/20">
      <li
        v-for="item in items"
        :key="item.name"
        class="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 text-sm"
      >
        <span class="min-w-0 flex-1 truncate font-medium text-ink">{{ item.title || item.name }}</span>
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
          :loading="running(item.name)"
          :disabled="busy || apply.isPending.value"
          @click="apply.mutate([item.name])"
        >
          {{ t('plugins.updates.one') }}
        </Button>
      </li>
    </ul>
  </section>
</template>
