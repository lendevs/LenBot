<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery } from '@tanstack/vue-query'
import { ExternalLink, RefreshCw } from '@lucide/vue'
import { keys } from '../../api/query'
import { systemApi } from '../../api/system'
import { readUpdates } from '../../api/hostStore'
import { formatDateTime } from '../../i18n/format'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import Skeleton from '../../ui/Skeleton.vue'
import Switch from '../../ui/Switch.vue'

const { t } = useI18n()
const current = useQuery({ queryKey: keys.system.updates(), queryFn: ({ signal }) => systemApi.updates(signal) })
// Asks GitHub or the update controller, so only on request.
const releases = useQuery({
  queryKey: keys.system.releases(),
  queryFn: ({ signal }) => systemApi.releases(signal),
  enabled: false,
  staleTime: Infinity,
})
const prerelease = ref(false)
const visible = computed(() => (releases.data.value ?? []).filter((item) => prerelease.value || !item.prerelease))
const data = computed(() => current.data.value)
const check = computed(() => data.value?.check)
const summary = computed(() => {
  const value = check.value
  if (!value) return ''
  if (value.update_available) return t('system.updates.available', { version: value.latest })
  if (value.error) return t('system.updates.checkFailed')
  if (value.checked_at)
    return value.latest_prerelease
      ? t('system.updates.latestWithPre', { version: value.latest_prerelease })
      : t('system.updates.latest')
  return value.enabled ? t('system.updates.notChecked') : t('system.updates.checkOff')
})
async function checkNow() {
  await releases.refetch()
  void current.refetch()
  void readUpdates()
}
const open = useMutation({
  mutationFn: () => systemApi.updaterSession(),
  onSuccess: (session) => window.location.assign(session.url),
})
</script>

<template>
  <Skeleton v-if="current.isPending.value" :lines="5" />
  <ErrorNote v-else-if="current.isError.value" :title="t('system.updates.readFailed')" :error="current.error.value" :retry="current.refetch" />
  <div v-else-if="data" class="flex min-w-0 flex-col gap-4">
    <section
      class="flex flex-wrap items-center justify-between gap-4 rounded-xl border p-5"
      :class="check?.update_available ? 'border-brand/40 bg-brand-soft' : 'border-line bg-surface'"
    >
      <div class="flex flex-col gap-0.5">
        <span class="text-sm text-muted">{{ t('system.updates.current') }}</span>
        <strong class="text-xl font-semibold text-ink tabular">{{ data.version }}</strong>
      </div>
      <p v-if="summary" class="flex flex-wrap items-center gap-2 text-sm" :class="check?.update_available ? 'font-semibold text-primary' : 'text-ink-2'">
        <span class="size-2 rounded-full" :class="check?.update_available ? 'bg-brand' : 'bg-subtle'" aria-hidden="true" />
        {{ summary }}
        <span v-if="check?.checked_at" class="font-normal text-muted">· {{ formatDateTime(check.checked_at) }}</span>
      </p>
    </section>
    <ErrorNote v-if="check?.error" :title="t('system.updates.checkFailed')" :error="check.error" />
    <ErrorNote v-if="data.status?.error" :title="t('system.updates.controllerError')" :error="data.status.error" />

    <section class="flex min-w-0 flex-col gap-3 rounded-xl border border-line bg-surface p-5">
      <h3 class="text-base font-semibold">{{ t('system.updates.howTitle') }}</h3>
      <template v-if="data.managed">
        <ul class="flex list-disc flex-col gap-1.5 pl-5 text-sm text-ink-2">
          <li v-for="line in data.notice ?? []" :key="line">{{ line }}</li>
        </ul>
        <div>
          <Button variant="primary" :icon-right="ExternalLink" :loading="open.isPending.value" @click="open.mutate()">
            {{ t('system.updates.open') }}
          </Button>
        </div>
        <ErrorNote v-if="open.isError.value" :title="t('system.updates.openFailed')" :error="open.error.value" />
      </template>
      <p v-else class="text-sm text-ink-2">{{ t('system.updates.source') }}</p>
    </section>

    <section class="flex min-w-0 flex-col gap-3 rounded-xl border border-line bg-surface p-5">
      <header class="flex flex-wrap items-center justify-between gap-3">
        <h3 class="text-base font-semibold">{{ t('system.updates.releases') }}</h3>
        <div class="flex flex-wrap items-center gap-4">
          <Field :label="t('system.updates.prerelease')" inline>
            <Switch v-model="prerelease" />
          </Field>
          <Button size="sm" :icon="RefreshCw" :loading="releases.isFetching.value" @click="checkNow">{{ t('system.updates.check') }}</Button>
        </div>
      </header>
      <ErrorNote v-if="releases.isError.value" :title="t('system.updates.releasesFailed')" :error="releases.error.value" />
      <p v-if="releases.data.value && !visible.length" class="text-sm text-muted">{{ t('system.updates.none') }}</p>
      <ol v-if="visible.length" class="flex list-none flex-col divide-y divide-line">
        <li v-for="item in visible" :key="item.tag" class="flex flex-col gap-2 py-4 first:pt-1">
          <h4 class="flex flex-wrap items-center gap-2 text-sm font-semibold text-ink">
            {{ item.tag }}
            <Badge v-if="item.newer" tone="brand">{{ t('system.updates.newer') }}</Badge>
            <Badge v-if="item.version === data.version">{{ t('system.updates.installed') }}</Badge>
            <Badge v-if="item.prerelease" tone="warning">{{ t('system.updates.pre') }}</Badge>
          </h4>
          <pre class="font-sans text-sm whitespace-pre-wrap text-muted">{{ item.notes }}</pre>
        </li>
      </ol>
    </section>
  </div>
</template>
