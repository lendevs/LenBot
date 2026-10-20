<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { Link2, MonitorSmartphone, RefreshCw } from '@lucide/vue'
import { capabilitiesApi, type BrowserSettings } from '../../api/capabilities'
import { keys } from '../../api/query'
import { useUnsavedChanges } from '../../composables/useUnsavedChanges.js'
import { developerDetails } from '../../composables/useDeveloperMode.js'
import { readPendingRestart } from '../../host/store.js'
import { groupLabel } from '../../layouts/shell/scenes'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import CodeBlock from '../../ui/CodeBlock.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import FormSection from '../../ui/FormSection.vue'
import Input from '../../ui/Input.vue'
import NumberInput from '../../ui/NumberInput.vue'
import SaveBar from '../../ui/SaveBar.vue'
import Skeleton from '../../ui/Skeleton.vue'
import Switch from '../../ui/Switch.vue'
import { confirm } from '../../ui/confirm'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'
import RawRecord from '../groups/tasks/RawRecord.vue'

const { t } = useI18n()
const client = useQueryClient()
const browser = useQuery({ queryKey: keys.host.browser(), queryFn: ({ signal }) => capabilitiesApi.browser(signal) })
const state = computed(() => browser.data.value)
const blank = (): BrowserSettings => ({
  socket: '',
  browser_instance_id: null,
  binary: '',
  home: '',
  timeout_seconds: 65,
  max_response_bytes: 16000000,
})
const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const draft = ref<BrowserSettings | null>(null)
watch(
  () => state.value?.saved,
  (next, previous) => {
    if (next === undefined) return
    if (previous === undefined || same(draft.value, previous)) draft.value = next && copy(next)
  },
  { immediate: true },
)
const dirty = computed(() => state.value !== undefined && !same(draft.value, state.value.saved))
useUnsavedChanges(dirty, { keep: ['tab'] })
const errors = computed(() => {
  const value = draft.value
  const result: Record<string, string> = {}
  if (!value) return result
  for (const key of ['socket', 'binary', 'home'] as const) {
    if (!value[key].trim()) result[key] = t('capabilities.required')
    else if (!value[key].startsWith('/')) result[key] = t('capabilities.worker.absolute')
  }
  if (value.timeout_seconds === null) result.timeout = t('capabilities.required')
  if (value.max_response_bytes === null) result.bytes = t('capabilities.required')
  return result
})
const invalid = computed(() => Object.keys(errors.value).length > 0)
const save = useMutation({
  mutationFn: () => capabilitiesApi.saveBrowser(draft.value),
  onSuccess: (next) => {
    client.setQueryData(keys.host.browser(), next)
    draft.value = next.saved && copy(next.saved)
    void readPendingRestart()
    toast.success(t('capabilities.savedRestart'))
  },
})
const saveError = computed(() => (save.isError.value ? describeError(save.error.value, t('ui.error.network')).message : null))

const failed = (error: unknown) => toast.error(t('capabilities.failed'), { detail: describeError(error, t('ui.error.network')).message })
const status = ref<Record<string, unknown> | null>(null)
const devices = ref<{ device_id: string; label: string }[] | null>(null)
const check = useMutation({
  mutationFn: async () => ({ status: await capabilitiesApi.browserStatus(), devices: (await capabilitiesApi.browserDevices()).devices }),
  onSuccess: (result) => {
    status.value = result.status
    devices.value = result.devices
  },
})
const pairing = ref('')
const pair = useMutation({
  mutationFn: () => capabilitiesApi.pairBrowser(),
  onSuccess: (result) => (pairing.value = result.pairing_link),
  onError: failed,
})
const revoke = useMutation({
  mutationFn: async (device: string) => {
    await capabilitiesApi.revokeDevice(device)
    return (await capabilitiesApi.browserDevices()).devices
  },
  onSuccess: (list) => {
    devices.value = list
    toast.success(t('capabilities.browser.revoked'))
  },
  onError: failed,
})
async function confirmRevoke(device: string) {
  const sure = await confirm({
    title: t('capabilities.browser.revokeTitle'),
    message: t('capabilities.browser.revokeMessage'),
    confirmLabel: t('capabilities.browser.revoke'),
    tone: 'danger',
  })
  if (sure) revoke.mutate(device)
}
const release = useMutation({
  mutationFn: (task: { scene: string; id: number }) => capabilitiesApi.releaseBrowser(task.scene, task.id, null),
  onSuccess: () => {
    void browser.refetch()
    toast.success(t('capabilities.browser.released'))
  },
  onError: failed,
})
async function confirmRelease(task: { scene: string; id: number }) {
  const sure = await confirm({
    title: t('capabilities.browser.releaseTitle', { id: task.id }),
    confirmLabel: t('capabilities.browser.release'),
    tone: 'primary',
  })
  if (sure) release.mutate(task)
}
const finished = (value: string) => ['done', 'failed', 'cancelled'].includes(value)
</script>

<template>
  <Skeleton v-if="browser.isPending.value" :lines="6" />
  <ErrorNote v-else-if="browser.isError.value" :title="t('capabilities.browser.readFailed')" :error="browser.error.value" :retry="browser.refetch" />
  <div v-else-if="state" class="flex min-w-0 flex-col gap-4">
    <div class="flex min-w-0 flex-col gap-6 rounded-xl border border-line bg-surface p-5">
      <Field :label="t('capabilities.browser.on')" inline>
        <Switch :model-value="draft !== null" @update:model-value="(on: boolean) => (draft = on ? (state!.saved ? copy(state!.saved) : blank()) : null)" />
      </Field>
      <FormSection v-if="draft">
        <Field :label="t('capabilities.browser.socket')" required :error="errors.socket" wide>
          <Input v-model="draft.socket" mono />
        </Field>
        <Field :label="t('capabilities.browser.binary')" required :error="errors.binary" wide>
          <Input v-model="draft.binary" mono />
        </Field>
        <Field :label="t('capabilities.browser.home')" required :error="errors.home" wide>
          <Input v-model="draft.home" mono />
        </Field>
        <Field :label="t('capabilities.browser.instance')">
          <Input
            :model-value="draft.browser_instance_id ?? ''"
            mono
            @update:model-value="(value: string) => (draft!.browser_instance_id = value.trim() ? value : null)"
          />
        </Field>
        <Field :label="t('capabilities.browser.timeout')" :error="errors.timeout">
          <NumberInput v-model="draft.timeout_seconds" :min="1" :max="600" :snap="false" :steppers="false" :unit="t('capabilities.seconds')" />
        </Field>
        <Field :label="t('capabilities.browser.bytes')" :error="errors.bytes">
          <NumberInput v-model="draft.max_response_bytes" :min="1024" :steppers="false" unit="B" />
        </Field>
      </FormSection>
    </div>

    <section v-if="state.running" class="flex min-w-0 flex-col gap-3 rounded-xl border border-line bg-surface p-5">
      <header class="flex flex-wrap items-center justify-between gap-2">
        <h3 class="text-base font-semibold">{{ t('capabilities.browser.devices') }}</h3>
        <div class="flex items-center gap-2">
          <Button size="sm" :icon="RefreshCw" :loading="check.isPending.value" @click="check.mutate()">{{ t('capabilities.browser.check') }}</Button>
          <Button size="sm" :icon="Link2" :loading="pair.isPending.value" @click="pair.mutate()">{{ t('capabilities.browser.pair') }}</Button>
        </div>
      </header>
      <ErrorNote v-if="check.isError.value" :title="t('capabilities.browser.checkFailed')" :error="check.error.value" />
      <div v-if="pairing" class="flex flex-col gap-2 rounded-md bg-info-bg px-3 py-2 text-sm text-info">
        <p>{{ t('capabilities.browser.pairing') }}</p>
        <CodeBlock :code="pairing" :max-lines="4" />
      </div>
      <ul v-if="devices?.length" class="flex list-none flex-col divide-y divide-line">
        <li v-for="device in devices" :key="device.device_id" class="flex items-center gap-3 py-2">
          <MonitorSmartphone :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
          <span class="min-w-0 flex-1 truncate text-sm">{{ device.label }}</span>
          <Button size="sm" variant="danger-ghost" :loading="revoke.isPending.value && revoke.variables.value === device.device_id" @click="confirmRevoke(device.device_id)">
            {{ t('capabilities.browser.revoke') }}
          </Button>
        </li>
      </ul>
      <p v-else-if="devices" class="text-sm text-muted">{{ t('capabilities.browser.noDevices') }}</p>
      <RawRecord v-if="developerDetails && status" :label="t('capabilities.browser.status')" :code="status" />
    </section>

    <section v-if="state.occupied.length" class="flex min-w-0 flex-col gap-3 rounded-xl border border-line bg-surface p-5">
      <h3 class="text-base font-semibold">{{ t('capabilities.browser.occupied') }}</h3>
      <ul class="flex list-none flex-col divide-y divide-line">
        <li v-for="task in state.occupied" :key="`${task.scene}:${task.id}`" class="flex items-center gap-3 py-2">
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm text-ink">{{ task.goal }}</p>
            <p class="truncate text-xs text-muted">{{ groupLabel(task.scene) }} · #{{ task.id }}</p>
          </div>
          <Badge>{{ t(`groups.tasks.status.${task.status}`, task.status) }}</Badge>
          <Button size="sm" variant="ghost" :disabled="!finished(task.status)" :loading="release.isPending.value && release.variables.value?.id === task.id" @click="confirmRelease(task)">
            {{ t('capabilities.browser.release') }}
          </Button>
        </li>
      </ul>
    </section>
    <SaveBar :dirty="dirty" :saving="save.isPending.value" :error="saveError" :invalid="invalid" @save="save.mutate()" @discard="draft = state!.saved && copy(state!.saved)" />
  </div>
</template>
