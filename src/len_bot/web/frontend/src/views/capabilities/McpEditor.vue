<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { ArrowLeft, Plug, PlugZap, Plus, Trash2, X } from '@lucide/vue'
import { capabilitiesApi, type McpService, type McpState } from '../../api/capabilities'
import { keys } from '../../api/query'
import { useUnsavedChanges } from '../../composables/useUnsavedChanges'
import { developerDetails } from '../../composables/useDeveloperMode'
import { readPendingRestart } from '../../api/hostStore'
import { formatDateTime } from '../../i18n/format'
import { groupLabel } from '../../layouts/shell/scenes'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import CodeBlock from '../../ui/CodeBlock.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import FormSection from '../../ui/FormSection.vue'
import IconButton from '../../ui/IconButton.vue'
import Input from '../../ui/Input.vue'
import NumberInput from '../../ui/NumberInput.vue'
import SaveBar from '../../ui/SaveBar.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import Switch from '../../ui/Switch.vue'
import Textarea from '../../ui/Textarea.vue'
import { confirm } from '../../ui/confirm'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'
import RawRecord from '../groups/tasks/RawRecord.vue'
import ScenePicker from '../plugins/schema/ScenePicker.vue'
import { mcpTone } from './status'

/** `name` is null while adding a service. */
const props = defineProps<{ name: string | null; state: McpState; wide: boolean }>()
const emit = defineEmits<{ back: []; saved: [name: string]; removed: [] }>()

const { t } = useI18n()
const client = useQueryClient()

interface Pair {
  key: string
  value: string
  /** Saved before: the value is not sent back, and an empty one keeps it. */
  kept: boolean
}
interface Draft {
  name: string
  enabled: boolean
  scenes: string[]
  timeout_seconds: number | null
  max_response_bytes: number | null
  type: 'stdio' | 'http'
  command: string
  args: string
  cwd: string
  url: string
  pairs: Pair[]
}
function draftOf(name: string | null): Draft {
  const saved = name ? props.state.saved[name] : undefined
  const transport = saved?.transport
  const values = transport ? (transport.type === 'stdio' ? transport.env : transport.headers) : {}
  return {
    name: name ?? '',
    enabled: saved?.enabled ?? true,
    scenes: [...(saved?.scenes ?? [])],
    timeout_seconds: saved?.timeout_seconds ?? 30,
    max_response_bytes: saved?.max_response_bytes ?? 1048576,
    type: transport?.type ?? 'stdio',
    command: transport?.type === 'stdio' ? transport.command : '',
    args: transport?.type === 'stdio' ? transport.args.join('\n') : '',
    cwd: transport?.type === 'stdio' ? transport.cwd : '.',
    url: transport?.type === 'http' ? transport.url : '',
    pairs: Object.entries(values ?? {}).map(([key, value]) => ({
      key,
      value: value ?? '',
      kept: value === null,
    })),
  }
}
const initial = computed(() => draftOf(props.name))
const copy = (value: Draft): Draft => JSON.parse(JSON.stringify(value)) as Draft
const draft = ref<Draft>(copy(initial.value))
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
watch(initial, (next, previous) => {
  if (!previous || same(draft.value, previous)) draft.value = copy(next)
})
/** Set once this editor saved or removed its service, right before the list selects another one. */
const finished = ref(false)
const dirty = computed(
  () =>
    !finished.value &&
    (props.name === null ? Boolean(draft.value.name.trim()) : !same(draft.value, initial.value)),
)
useUnsavedChanges(dirty, { keep: ['tab'] })

const NAME = /^[a-z][a-z0-9_]{0,23}$/
const errors = computed(() => {
  const value = draft.value
  const result: Record<string, string> = {}
  const name = value.name.trim()
  if (props.name === null) {
    if (!NAME.test(name) || name.includes('__')) result.name = t('capabilities.mcp.nameRule')
    else if (name in props.state.saved) result.name = t('capabilities.mcp.nameTaken')
  }
  if (value.enabled && !value.scenes.length) result.scenes = t('capabilities.mcp.scenesRequired')
  if (value.type === 'stdio') {
    if (!value.command.trim()) result.command = t('capabilities.required')
    if (!value.cwd.trim()) result.cwd = t('capabilities.required')
  } else if (!/^https?:\/\/[^/?#]+/.test(value.url.trim())) result.url = t('capabilities.mcp.urlRule')
  if (value.timeout_seconds === null) result.timeout = t('capabilities.required')
  if (value.max_response_bytes === null) result.bytes = t('capabilities.required')
  const names = value.pairs.map((pair) => pair.key.trim()).filter(Boolean)
  if (new Set(names).size !== names.length) result.pairs = t('capabilities.mcp.pairsRepeat')
  return result
})
const invalid = computed(() => Object.keys(errors.value).length > 0)

function body(): McpService {
  const value = draft.value
  const pairs = Object.fromEntries(
    value.pairs
      .filter((pair) => pair.key.trim())
      .map((pair) => [pair.key.trim(), pair.kept && pair.value === '' ? null : pair.value]),
  ) as Record<string, string | null>
  return {
    enabled: value.enabled,
    scenes: value.scenes,
    timeout_seconds: value.timeout_seconds ?? 30,
    max_response_bytes: value.max_response_bytes ?? 1048576,
    transport:
      value.type === 'stdio'
        ? {
            type: 'stdio',
            command: value.command.trim(),
            args: value.args
              .split('\n')
              .map((item) => item.trim())
              .filter(Boolean),
            cwd: value.cwd.trim(),
            env: pairs,
          }
        : { type: 'http', url: value.url.trim(), headers: pairs },
  }
}
const accept = (state: McpState) => {
  client.setQueryData(keys.host.mcp(), state)
  void readPendingRestart()
}
const save = useMutation({
  mutationFn: () => capabilitiesApi.saveMcp(draft.value.name.trim(), body()),
  onSuccess: (state) => {
    accept(state)
    toast.success(t('capabilities.savedRestart'))
    finished.value = true
    emit('saved', draft.value.name.trim())
  },
})
const remove = useMutation({
  mutationFn: () => capabilitiesApi.removeMcp(props.name!),
  onSuccess: (state) => {
    accept(state)
    toast.success(t('capabilities.mcp.removed'))
    finished.value = true
    emit('removed')
  },
  onError: (error) =>
    toast.error(t('capabilities.failed'), { detail: describeError(error, t('ui.error.network')).message }),
})
async function confirmRemove() {
  const sure = await confirm({
    title: t('capabilities.mcp.removeTitle', { name: props.name }),
    message: t('capabilities.mcp.removeMessage'),
    confirmLabel: t('common.delete'),
    tone: 'danger',
  })
  if (sure) remove.mutate()
}

const running = computed(() =>
  props.name ? props.state.running.find((item) => item.name === props.name) : undefined,
)
const control = useMutation({
  mutationFn: (action: 'connect' | 'disconnect') =>
    action === 'connect'
      ? capabilitiesApi.connectMcp(props.name!)
      : capabilitiesApi.disconnectMcp(props.name!),
  onSuccess: (state, action) => {
    client.setQueryData(keys.host.mcp(), state)
    if (state.result?.status === 'failed')
      toast.error(t('capabilities.mcp.connectFailed'), { detail: state.result.error ?? undefined })
    else toast.success(t(`capabilities.mcp.${action}ed`))
  },
  onError: (error) =>
    toast.error(t('capabilities.failed'), { detail: describeError(error, t('ui.error.network')).message }),
})
async function reconnect() {
  const sure = await confirm({
    title: t('capabilities.mcp.reconnectTitle', { name: props.name }),
    message: t('capabilities.mcp.reconnectMessage'),
    confirmLabel: t('capabilities.mcp.reconnect'),
    tone: 'primary',
  })
  if (sure) control.mutate('connect')
}

const transports = computed(() => [
  { value: 'stdio' as const, label: t('capabilities.mcp.stdio') },
  { value: 'http' as const, label: t('capabilities.mcp.http') },
])
const setPair = (index: number, patch: Partial<Pair>) =>
  (draft.value.pairs = draft.value.pairs.map((pair, at) => (at === index ? { ...pair, ...patch } : pair)))
const saveError = computed(() =>
  save.isError.value ? describeError(save.error.value, t('ui.error.network')).message : null,
)
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <div class="flex min-w-0 items-center gap-2">
      <Button v-if="!wide" variant="ghost" size="sm" :icon="ArrowLeft" class="-ml-2" @click="emit('back')">
        {{ t('capabilities.mcp.all') }}
      </Button>
      <h2 class="min-w-0 flex-1 truncate text-base font-semibold" :class="!wide && 'sr-only'">
        {{ name ?? t('capabilities.mcp.add') }}
      </h2>
      <Button
        v-if="name"
        size="sm"
        variant="danger-ghost"
        :icon="Trash2"
        :loading="remove.isPending.value"
        @click="confirmRemove"
      >
        {{ t('capabilities.mcp.remove') }}
      </Button>
    </div>

    <section v-if="running" class="flex flex-col gap-3 rounded-xl border border-line bg-surface p-5">
      <div class="flex flex-wrap items-center gap-2">
        <Badge :tone="mcpTone(running.status)" dot>
          {{ t(`capabilities.mcp.status.${running.status}`, running.status) }}
        </Badge>
        <span class="min-w-0 flex-1 truncate text-sm text-muted">
          {{ running.scenes.map(groupLabel).join(t('personas.separator')) || t('capabilities.mcp.noGroups') }}
        </span>
        <Button
          size="sm"
          :icon="PlugZap"
          :disabled="running.status === 'disabled'"
          :loading="control.isPending.value && control.variables.value === 'connect'"
          @click="reconnect"
        >
          {{ t('capabilities.mcp.reconnect') }}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          :icon="Plug"
          :disabled="!['running', 'connecting'].includes(running.status)"
          :loading="control.isPending.value && control.variables.value === 'disconnect'"
          @click="control.mutate('disconnect')"
        >
          {{ t('capabilities.mcp.disconnect') }}
        </Button>
      </div>
      <ErrorNote v-if="running.error" :title="t('capabilities.mcp.connectFailed')" :error="running.error" />
      <details v-if="running.tools.length">
        <summary class="cursor-pointer text-sm font-medium text-ink-2">
          {{ t('capabilities.mcp.tools', { n: running.tools.length }, running.tools.length) }}
        </summary>
        <ul class="mt-2 flex list-none flex-col divide-y divide-line">
          <li
            v-for="tool in running.tools"
            :key="tool.name"
            class="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2"
          >
            <code class="rounded-sm bg-fill px-1.5 py-0.5 font-mono text-sm">{{ tool.name }}</code>
            <span class="min-w-0 text-sm text-ink-2">{{ tool.description }}</span>
          </li>
        </ul>
      </details>
      <details v-if="running.errors.length">
        <summary class="cursor-pointer text-sm font-medium text-error">
          {{ t('capabilities.mcp.errors', { n: running.errors.length }, running.errors.length) }}
        </summary>
        <ul class="mt-2 flex list-none flex-col gap-2">
          <li v-for="(item, index) in running.errors" :key="index" class="flex flex-col gap-1">
            <span class="text-xs text-muted tabular">
              {{ formatDateTime(item.at, { withSeconds: true }) }}
            </span>
            <CodeBlock :code="item.error" :max-lines="6" />
          </li>
        </ul>
      </details>
      <RawRecord v-if="developerDetails" :label="t('capabilities.mcp.raw')" :code="running" />
    </section>
    <p v-else-if="name" class="rounded-md bg-warning-bg px-3 py-2 text-sm text-warning">
      {{ t('capabilities.mcp.notRunning') }}
    </p>

    <div class="flex min-w-0 flex-col gap-6 rounded-xl border border-line bg-surface p-5">
      <FormSection>
        <Field
          v-if="name === null"
          :label="t('capabilities.mcp.name')"
          required
          :error="draft.name ? errors.name : null"
        >
          <Input v-model="draft.name" mono placeholder="search_docs" autofocus />
        </Field>
        <Field :label="t('capabilities.mcp.enabled')" inline :class="name === null ? '' : 'sm:col-span-2'">
          <Switch v-model="draft.enabled" />
        </Field>
        <Field :label="t('capabilities.mcp.scenes')" wide :error="dirty ? errors.scenes : null">
          <ScenePicker
            :model-value="draft.scenes"
            :choices="state.scenes"
            @update:model-value="(value) => (draft.scenes = (value as string[] | null) ?? [])"
          />
        </Field>
      </FormSection>
      <FormSection :title="t('capabilities.mcp.transport')">
        <div class="sm:col-span-2">
          <SegmentedControl
            v-model="draft.type"
            :options="transports"
            :label="t('capabilities.mcp.transport')"
          />
        </div>
        <template v-if="draft.type === 'stdio'">
          <Field :label="t('capabilities.mcp.command')" required :error="errors.command">
            <Input v-model="draft.command" mono placeholder="npx" />
          </Field>
          <Field :label="t('capabilities.mcp.cwd')" required :error="errors.cwd">
            <Input v-model="draft.cwd" mono />
          </Field>
          <Field :label="t('capabilities.mcp.args')" wide>
            <Textarea
              v-model="draft.args"
              :rows="2"
              mono
              :placeholder="t('capabilities.mcp.argsPlaceholder')"
            />
          </Field>
        </template>
        <Field v-else :label="t('capabilities.mcp.url')" required wide :error="draft.url ? errors.url : null">
          <Input v-model="draft.url" type="url" mono placeholder="http://127.0.0.1:8000/mcp" />
        </Field>
      </FormSection>
      <FormSection
        :title="draft.type === 'stdio' ? t('capabilities.mcp.env') : t('capabilities.mcp.headers')"
        :columns="1"
      >
        <ul v-if="draft.pairs.length" class="flex list-none flex-col gap-2">
          <li
            v-for="(pair, index) in draft.pairs"
            :key="index"
            class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_auto] items-center gap-2"
          >
            <Input
              :model-value="pair.key"
              mono
              :disabled="pair.kept"
              :aria-label="t('capabilities.mcp.pairName')"
              :placeholder="t('capabilities.mcp.pairName')"
              @update:model-value="(value: string) => setPair(index, { key: value })"
            />
            <Input
              :model-value="pair.value"
              type="password"
              mono
              autocomplete="new-password"
              :aria-label="t('capabilities.mcp.pairValue')"
              :placeholder="pair.kept ? t('plugins.form.secretKept') : t('capabilities.mcp.pairValue')"
              @update:model-value="(value: string) => setPair(index, { value })"
            />
            <IconButton
              :icon="X"
              :label="t('common.delete')"
              variant="ghost"
              size="sm"
              @click="draft.pairs = draft.pairs.filter((_, at) => at !== index)"
            />
          </li>
        </ul>
        <p v-if="errors.pairs" class="text-xs text-error">{{ errors.pairs }}</p>
        <div>
          <Button
            size="sm"
            variant="ghost"
            :icon="Plus"
            class="-ml-2"
            @click="draft.pairs = [...draft.pairs, { key: '', value: '', kept: false }]"
          >
            {{ t('capabilities.mcp.addPair') }}
          </Button>
        </div>
      </FormSection>
      <FormSection :title="t('capabilities.mcp.limits')">
        <Field :label="t('capabilities.mcp.timeout')" :error="errors.timeout">
          <NumberInput
            v-model="draft.timeout_seconds"
            :min="0.1"
            :max="300"
            :snap="false"
            :steppers="false"
            :unit="t('capabilities.seconds')"
          />
        </Field>
        <Field :label="t('capabilities.mcp.bytes')" :error="errors.bytes">
          <NumberInput
            v-model="draft.max_response_bytes"
            :min="1024"
            :max="10000000"
            :steppers="false"
            unit="B"
          />
        </Field>
      </FormSection>
    </div>
    <SaveBar
      :dirty="dirty"
      :saving="save.isPending.value"
      :error="saveError"
      :invalid="invalid"
      @save="save.mutate()"
      @discard="draft = copy(initial)"
    />
  </div>
</template>
