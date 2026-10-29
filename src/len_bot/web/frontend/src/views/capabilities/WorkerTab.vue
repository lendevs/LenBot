<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ArrowUpRight, ChevronDown } from '@lucide/vue'
import {
  capabilitiesApi,
  capabilitiesOf,
  PACKAGE_HOSTS,
  type Egress,
  type Worker,
} from '../../api/capabilities'
import { keys } from '../../api/query'
import { groupsTarget } from '../groups/route'
import { settingsApi } from '../../api/settings'
import { useUnsavedChanges } from '../../composables/useUnsavedChanges'
import { readPendingRestart } from '../../api/hostStore'
import Button from '../../ui/Button.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import FormSection from '../../ui/FormSection.vue'
import Input from '../../ui/Input.vue'
import NumberInput from '../../ui/NumberInput.vue'
import SaveBar from '../../ui/SaveBar.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import Select from '../../ui/Select.vue'
import Skeleton from '../../ui/Skeleton.vue'
import Switch from '../../ui/Switch.vue'
import TagInput from '../../ui/TagInput.vue'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

const { t } = useI18n()
const client = useQueryClient()
const settings = useQuery({
  queryKey: keys.host.settings(),
  queryFn: ({ signal }) => settingsApi.read(signal),
})
const saved = computed(() => (settings.data.value ? capabilitiesOf(settings.data.value).worker : undefined))
const defaults = useQuery({
  queryKey: keys.host.workerDefaults(),
  queryFn: ({ signal }) => capabilitiesApi.workerDefaults(signal),
  staleTime: Infinity,
})
const hasModel = computed(() => {
  const models = settings.data.value?.saved.models as { roles?: { worker?: unknown } } | undefined
  return Boolean(models?.roles?.worker)
})

const fresh = (): Worker => ({
  docker_binary: '',
  docker_host: 'unix:///var/run/docker.sock',
  image: '',
  workspace_root: '',
  runtime_root: '',
  delivery_root: '',
  storage_pool: null,
  skills_directory: null,
  uid: null,
  gid: null,
  cpus: 2,
  memory: '2g',
  tmpfs_size: '256m',
  pids_limit: 512,
  command_timeout_seconds: 30,
  max_running: 4,
  max_containers: 8,
  max_scene_containers: 4,
  max_calls: 40,
  max_request_bytes: 8 * 1024 * 1024,
  max_response_bytes: 64 * 1024 * 1024,
  max_tokens: null,
  compaction_reserve_tokens: 16384,
  compaction_keep_recent_tokens: 20000,
  active_timeout_seconds: 1800,
  input_timeout_seconds: 1800,
  max_file_bytes: 25 * 1024 * 1024,
  max_delivery_bytes: 500 * 1024 * 1024,
  max_workspace_bytes: 2 * 1024 ** 3,
  disk_reserve_bytes: 5 * 1024 ** 3,
  disk_stop_bytes: 2 * 1024 ** 3,
  workspace_retention_days: 14,
  storage_check_seconds: 30,
  input_support: 'text',
  model_reasoning: null,
  egress: {
    mode: 'off',
    allowed_hosts: [],
    max_task_upload_bytes: 20 * 1024 * 1024,
    max_task_bytes: 524288000,
    max_scene_daily_bytes: 2147483648,
    max_connections: 16,
    bytes_per_second: 8388608,
    connect_timeout_seconds: 30,
    header_timeout_seconds: 30,
  },
  mcp: false,
})
const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const draft = ref<Worker | null>(null)
/** The settings kept while the switch is off, so turning it back on restores them. */
const parked = ref<Worker | null>(null)
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
watch(
  saved,
  (next, previous) => {
    if (next === undefined) return
    if (previous === undefined || same(draft.value, previous)) draft.value = next && copy(next)
  },
  { immediate: true },
)
/** The draft while the switch is on; the form block only renders then. */
const form = computed(() => draft.value!)
const dirty = computed(() => saved.value !== undefined && !same(draft.value, saved.value))
useUnsavedChanges(dirty, { keep: ['tab'] })
function toggle(on: boolean) {
  if (on)
    draft.value = parked.value ?? (saved.value ? copy(saved.value) : { ...fresh(), ...defaults.data.value })
  else {
    parked.value = draft.value
    draft.value = null
  }
}

type NumberKey = { [K in keyof Worker]-?: Worker[K] extends number | null ? K : never }[keyof Worker]
type EgressKey = { [K in keyof Egress]: Egress[K] extends number | null ? K : never }[keyof Egress]
const limits: { key: NumberKey; unit?: string; decimals?: boolean }[] = [
  { key: 'cpus', decimals: true },
  { key: 'pids_limit' },
  { key: 'command_timeout_seconds', unit: 's', decimals: true },
  { key: 'max_running' },
  { key: 'max_containers' },
  { key: 'max_scene_containers' },
  { key: 'max_calls' },
  { key: 'max_request_bytes', unit: 'B' },
  { key: 'max_response_bytes', unit: 'B' },
  { key: 'active_timeout_seconds', unit: 's', decimals: true },
  { key: 'input_timeout_seconds', unit: 's', decimals: true },
  { key: 'max_file_bytes', unit: 'B' },
  { key: 'max_delivery_bytes', unit: 'B' },
  { key: 'max_workspace_bytes', unit: 'B' },
  { key: 'disk_reserve_bytes', unit: 'B' },
  { key: 'disk_stop_bytes', unit: 'B' },
  { key: 'workspace_retention_days', decimals: true },
  { key: 'compaction_reserve_tokens', unit: 'tokens' },
  { key: 'compaction_keep_recent_tokens', unit: 'tokens' },
]
const egressLimits: { key: EgressKey; unit?: string; decimals?: boolean }[] = [
  { key: 'max_task_upload_bytes', unit: 'B' },
  { key: 'max_task_bytes', unit: 'B' },
  { key: 'max_scene_daily_bytes', unit: 'B' },
  { key: 'max_connections' },
  { key: 'bytes_per_second', unit: 'B/s' },
  { key: 'connect_timeout_seconds', unit: 's', decimals: true },
  { key: 'header_timeout_seconds', unit: 's', decimals: true },
]
const paths = ['docker_binary', 'workspace_root', 'runtime_root', 'delivery_root'] as const
const SIZE = /^[1-9][0-9]*[kmgKMG]$/
/** POSIX absolute paths and Windows drive or UNC paths; the host checks the path on its own platform. */
const ABSOLUTE = /^(\/|[A-Za-z]:[\\/]|\\\\)/
const DOCKER_HOST = /^(unix:\/\/\/.|npipe:\/\/\/\/\.\/pipe\/[A-Za-z0-9_.-]+$)/
/** Same rule as the host: a lowercase domain, or *. and a domain for its subdomains. */
const HOST = /^(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]([a-z0-9-]{0,61}[a-z0-9])?$/

const errors = computed(() => {
  const value = draft.value
  const result: Record<string, string> = {}
  if (!value) return result
  const required = t('capabilities.required')
  if (!value.image.trim()) result.image = required
  for (const key of paths) {
    if (!value[key].trim()) result[key] = required
    else if (!ABSOLUTE.test(value[key])) result[key] = t('capabilities.worker.absolute')
  }
  if (value.skills_directory && !ABSOLUTE.test(value.skills_directory))
    result.skills_directory = t('capabilities.worker.absolute')
  if (!DOCKER_HOST.test(value.docker_host)) result.docker_host = t('capabilities.worker.dockerHostRule')
  if (value.uid === null) result.uid = required
  if (value.gid === null) result.gid = required
  if (value.model_reasoning === null) result.model_reasoning = t('capabilities.worker.pickReasoning')
  if (!SIZE.test(value.memory)) result.memory = t('capabilities.worker.size')
  if (!SIZE.test(value.tmpfs_size)) result.tmpfs_size = t('capabilities.worker.size')
  for (const { key } of limits) if (value[key] === null) result[key] = required
  for (const { key } of egressLimits) if (value.egress[key] === null) result[`egress.${key}`] = required
  if (value.egress.mode === 'allowlist' && value.egress.allowed_hosts.length === 0)
    result.allowed_hosts = t('capabilities.worker.hostsRequired')
  const badHost = value.egress.allowed_hosts.find((host) => !HOST.test(host))
  if (badHost) result.allowed_hosts = t('capabilities.worker.hostRule', { host: badHost })
  if (
    value.disk_stop_bytes !== null &&
    value.disk_reserve_bytes !== null &&
    value.disk_stop_bytes >= value.disk_reserve_bytes
  )
    result.disk_stop_bytes = t('capabilities.worker.diskOrder')
  return result
})
const invalid = computed(() => Object.keys(errors.value).length > 0)
/** Advanced limits open on their own when one of them needs fixing. */
const advanced = ref(false)
watch(invalid, () => {
  if (
    Object.keys(errors.value).some(
      (key) => key.startsWith('egress.') || limits.some((item) => item.key === key),
    )
  )
    advanced.value = true
})

const save = useMutation({
  mutationFn: () => capabilitiesApi.saveWorker(draft.value),
  onSuccess: (snapshot) => {
    client.setQueryData(keys.host.settings(), snapshot)
    const next = capabilitiesOf(snapshot).worker
    draft.value = next && copy(next)
    void readPendingRestart()
    toast.success(t('capabilities.savedRestart'))
  },
})
const saveError = computed(() =>
  save.isError.value ? describeError(save.error.value, t('ui.error.network')).message : null,
)
const reasoning = computed(() => [
  { value: 'yes', label: t('capabilities.worker.reasoningYes') },
  { value: 'no', label: t('capabilities.worker.reasoningNo') },
])
const reasoningValue = computed({
  get: () =>
    draft.value?.model_reasoning === null ? undefined : draft.value?.model_reasoning ? 'yes' : 'no',
  set: (value: string | undefined) => {
    if (draft.value) draft.value.model_reasoning = value === undefined ? null : value === 'yes'
  },
})
const inputs = computed(() => [
  { value: 'text' as const, label: t('capabilities.worker.textOnly') },
  { value: 'text-image' as const, label: t('capabilities.worker.withImages') },
])
const networkModes = computed(() =>
  (['off', 'allowlist', 'public'] as const).map((value) => ({
    value,
    label: t(`capabilities.worker.networkModes.${value}`),
  })),
)
function addPackageHosts() {
  if (!draft.value) return
  const hosts = draft.value.egress.allowed_hosts
  draft.value.egress.allowed_hosts = [...hosts, ...PACKAGE_HOSTS.filter((host) => !hosts.includes(host))]
}
</script>

<template>
  <Skeleton v-if="settings.isPending.value" :lines="8" />
  <ErrorNote
    v-else-if="settings.isError.value"
    :title="t('capabilities.worker.readFailed')"
    :error="settings.error.value"
    :retry="settings.refetch"
  />
  <div v-else-if="saved !== undefined" class="flex min-w-0 flex-col gap-4">
    <div class="flex min-w-0 flex-col gap-6 rounded-xl border border-line bg-surface p-5">
      <Field :label="t('capabilities.worker.on')" inline>
        <Switch :model-value="draft !== null" @update:model-value="toggle" />
      </Field>
      <template v-if="draft">
        <p
          v-if="!hasModel"
          class="flex flex-wrap items-center gap-2 rounded-md bg-info-bg px-3 py-2 text-sm text-info"
        >
          {{ t('capabilities.worker.followsChat') }}
          <Button
            size="sm"
            variant="ghost"
            :icon-right="ArrowUpRight"
            :to="{ name: 'host-models', query: { tab: 'roles' } }"
          >
            {{ t('capabilities.worker.toModels') }}
          </Button>
        </p>
        <FormSection :title="t('capabilities.worker.model')">
          <Field :label="t('capabilities.worker.reasoning')" required :error="errors.model_reasoning">
            <Select
              v-model="reasoningValue"
              :options="reasoning"
              :placeholder="t('capabilities.worker.pickReasoning')"
            />
          </Field>
          <Field :label="t('capabilities.worker.input')">
            <div>
              <SegmentedControl
                v-model="form.input_support"
                :options="inputs"
                :label="t('capabilities.worker.input')"
              />
            </div>
          </Field>
          <Field :label="t('capabilities.worker.maxTokens')">
            <NumberInput
              v-model="form.max_tokens"
              :min="1"
              :steppers="false"
              unit="tokens"
              :placeholder="t('capabilities.unlimited')"
            />
          </Field>
        </FormSection>
        <FormSection :title="t('capabilities.worker.abilities')">
          <Field :label="t('capabilities.worker.network')" wide>
            <div>
              <SegmentedControl
                v-model="form.egress.mode"
                :options="networkModes"
                :label="t('capabilities.worker.network')"
              />
            </div>
          </Field>
          <Field
            v-if="form.egress.mode === 'allowlist'"
            :label="t('capabilities.worker.allowedHosts')"
            required
            :error="errors.allowed_hosts"
            wide
          >
            <div class="flex min-w-0 flex-col items-start gap-2">
              <TagInput
                v-model="form.egress.allowed_hosts"
                placeholder="example.com、*.example.org"
                class="w-full"
              />
              <Button size="sm" variant="ghost" @click="addPackageHosts">
                {{ t('capabilities.worker.packageHosts') }}
              </Button>
            </div>
          </Field>
        </FormSection>
        <FormSection :title="t('capabilities.worker.runtime')">
          <Field :label="t('capabilities.worker.image')" required :error="errors.image">
            <Input v-model="form.image" mono />
          </Field>
          <Field :label="t('capabilities.worker.dockerBinary')" required :error="errors.docker_binary">
            <Input v-model="form.docker_binary" mono placeholder="/usr/local/bin/docker" />
          </Field>
          <Field :label="t('capabilities.worker.dockerHost')" required :error="errors.docker_host" wide>
            <Input v-model="form.docker_host" mono placeholder="unix:///var/run/docker.sock" />
          </Field>
          <Field :label="t('capabilities.worker.uid')" required :error="errors.uid">
            <NumberInput v-model="form.uid" :min="1" :steppers="false" />
          </Field>
          <Field :label="t('capabilities.worker.gid')" required :error="errors.gid">
            <NumberInput v-model="form.gid" :min="1" :steppers="false" />
          </Field>
          <Field :label="t('capabilities.worker.workspace')" required :error="errors.workspace_root" wide>
            <Input v-model="form.workspace_root" mono />
          </Field>
          <Field :label="t('capabilities.worker.runtimeRoot')" required :error="errors.runtime_root" wide>
            <Input v-model="form.runtime_root" mono />
          </Field>
          <Field :label="t('capabilities.worker.delivery')" required :error="errors.delivery_root" wide>
            <Input v-model="form.delivery_root" mono />
          </Field>
          <Field :label="t('capabilities.worker.skills')" :error="errors.skills_directory" wide>
            <Input
              :model-value="form.skills_directory ?? ''"
              mono
              :placeholder="t('capabilities.worker.skillsOff')"
              @update:model-value="(value: string) => (form.skills_directory = value.trim() ? value : null)"
            />
          </Field>
          <Field :label="t('capabilities.worker.memory')" :error="errors.memory">
            <Input v-model="form.memory" mono placeholder="2g" />
          </Field>
          <Field :label="t('capabilities.worker.tmpfs')" :error="errors.tmpfs_size">
            <Input v-model="form.tmpfs_size" mono placeholder="256m" />
          </Field>
        </FormSection>
        <FormSection :title="t('capabilities.worker.storage')" :columns="1">
          <p class="flex flex-wrap items-center gap-2 text-sm text-ink-2">
            <Button
              size="sm"
              variant="ghost"
              :icon-right="ArrowUpRight"
              :to="groupsTarget(undefined, 'tasks', { tab: 'resources' })"
            >
              {{ t('capabilities.worker.usage') }}
            </Button>
          </p>
        </FormSection>
        <section class="border-t border-line pt-6">
          <button
            type="button"
            class="flex w-full cursor-pointer items-center justify-between gap-3 rounded-sm text-left focus-visible:focus-ring"
            :aria-expanded="advanced"
            @click="advanced = !advanced"
          >
            <h3 class="text-base font-semibold text-ink">{{ t('capabilities.worker.advanced') }}</h3>
            <ChevronDown
              :size="18"
              class="text-subtle transition-transform"
              :class="advanced && 'rotate-180'"
              aria-hidden="true"
            />
          </button>
          <div v-if="advanced" class="mt-4 grid gap-x-5 gap-y-5 sm:grid-cols-2">
            <Field
              v-for="item in limits"
              :key="item.key"
              :label="t(`capabilities.worker.limits.${item.key}`)"
              :error="errors[item.key]"
            >
              <NumberInput
                v-model="form[item.key]"
                :min="item.decimals ? 0.001 : 1"
                :snap="!item.decimals"
                :steppers="false"
                :unit="item.unit"
              />
            </Field>
            <Field
              v-for="item in egressLimits"
              :key="item.key"
              :label="t(`capabilities.worker.egress.${item.key}`)"
              :error="errors[`egress.${item.key}`]"
            >
              <NumberInput
                v-model="form.egress[item.key]"
                :min="item.decimals ? 0.001 : 1"
                :snap="!item.decimals"
                :steppers="false"
                :unit="item.unit"
              />
            </Field>
          </div>
        </section>
      </template>
    </div>
    <SaveBar
      :dirty="dirty"
      :saving="save.isPending.value"
      :error="saveError"
      :invalid="invalid"
      @save="save.mutate()"
      @discard="draft = saved && copy(saved)"
    />
  </div>
</template>
