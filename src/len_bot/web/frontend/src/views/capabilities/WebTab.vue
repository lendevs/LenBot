<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  capabilitiesApi,
  capabilitiesOf,
  type Network,
  type WebRead,
  type WebSearch,
} from '../../api/capabilities'
import type { SavedProvider } from '../../api/models'
import { READ_APIS, READ_SERVICES, SEARCH_APIS, SEARCH_SERVICES } from '../../api/webServices'
import { keys } from '../../api/query'
import { settingsApi, type SettingsSnapshot } from '../../api/settings'
import { readPendingRestart } from '../../api/hostStore'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import FormSection from '../../ui/FormSection.vue'
import Button from '../../ui/Button.vue'
import Input from '../../ui/Input.vue'
import NumberInput from '../../ui/NumberInput.vue'
import SaveBar from '../../ui/SaveBar.vue'
import Select from '../../ui/Select.vue'
import Skeleton from '../../ui/Skeleton.vue'
import Switch from '../../ui/Switch.vue'
import Textarea from '../../ui/Textarea.vue'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const client = useQueryClient()
const settings = useQuery({
  queryKey: keys.host.settings(),
  queryFn: ({ signal }) => settingsApi.read(signal),
})

interface Draft {
  read: WebRead | null
  search: WebSearch | null
  fakeIp: string
  dns: string
}
const pick = (snapshot: SettingsSnapshot): Draft => {
  const saved = capabilitiesOf(snapshot)
  return {
    read: saved.web_read && { ...saved.web_read },
    search: saved.web_search && { ...saved.web_search },
    fakeIp: saved.network.fake_ip_networks.join('\n'),
    dns: saved.network.public_dns_url,
  }
}
const initial = computed(() => (settings.data.value ? pick(settings.data.value) : null))
const draft = ref<Draft | null>(null)
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const copy = (value: Draft): Draft => JSON.parse(JSON.stringify(value)) as Draft
watch(
  initial,
  (next, previous) => {
    if (next && (!previous || !draft.value || same(draft.value, previous))) draft.value = copy(next)
  },
  { immediate: true },
)
const changed = computed(() => {
  const value = draft.value
  const base = initial.value
  if (!value || !base) return { read: false, search: false, network: false }
  return {
    read: !same(value.read, base.read),
    search: !same(value.search, base.search),
    network: value.fakeIp !== base.fakeIp || value.dns !== base.dns,
  }
})
const providers = computed(() =>
  SEARCH_SERVICES.map((value) => ({ value, label: t(`capabilities.web.services.${value}`) })),
)
const readers = computed(() =>
  READ_SERVICES.map((value) => ({ value, label: t(`capabilities.web.services.${value}`) })),
)
const saved = computed(() =>
  Object.entries(
    (settings.data.value?.saved.models as { providers: Record<string, SavedProvider> } | undefined)
      ?.providers ?? {},
  ),
)
/** Saved connections whose protocol the chosen service accepts. */
const usable = (apis: string[] | null | undefined) =>
  saved.value
    .filter(([, value]) => apis?.includes(value.api))
    .map(([alias]) => ({ value: alias, label: alias }))
const searchConnections = computed(() =>
  usable(draft.value?.search && SEARCH_APIS[draft.value.search.provider]),
)
const readConnections = computed(() => usable(draft.value?.read && READ_APIS[draft.value.read.provider]))
const searchKeyed = computed(() => Boolean(draft.value?.search && SEARCH_APIS[draft.value.search.provider]))
const readKeyed = computed(() => Boolean(draft.value?.read && READ_APIS[draft.value.read.provider]))
// A connection that the newly chosen service cannot use is cleared.
watch(searchConnections, (options) => {
  const search = draft.value?.search
  if (search && !options.some((item) => item.value === search.connection)) search.connection = null
})
watch(readConnections, (options) => {
  const read = draft.value?.read
  if (read && !options.some((item) => item.value === read.connection)) read.connection = null
})
const dirty = computed(() => Object.values(changed.value).some(Boolean))
watch(dirty, (value) => emit('dirty', value), { immediate: true })
const readConnectionError = computed(() => {
  if (!draft.value?.read || !readKeyed.value) return null
  if (!readConnections.value.length) return t('capabilities.web.noConnection')
  if (!draft.value.read.connection) return t('capabilities.web.pickConnection')
  return null
})
const searchConnectionError = computed(() => {
  if (!draft.value?.search || !searchKeyed.value) return null
  if (!searchConnections.value.length) return t('capabilities.web.noConnection')
  if (!draft.value.search.connection) return t('capabilities.web.pickConnection')
  return null
})
const networks = computed(() =>
  (draft.value?.fakeIp ?? '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean),
)
const invalid = computed(() => {
  const value = draft.value
  if (!value) return true
  return (
    (searchKeyed.value && !value.search?.connection) ||
    (readKeyed.value && !value.read?.connection) ||
    (value.read !== null && value.read.timeout_seconds === null) ||
    (value.search !== null && (value.search.timeout_seconds === null || value.search.max_results === null)) ||
    !/^https?:\/\/[^/?#]+/.test(value.dns.trim())
  )
})

const saving = ref(false)
const saveError = ref<string | null>(null)
const saveRawError = ref<string | null>(null)
async function save() {
  const value = draft.value!
  saving.value = true
  saveError.value = null
  saveRawError.value = null
  try {
    let snapshot: SettingsSnapshot | null = null
    if (changed.value.read) snapshot = await capabilitiesApi.saveWebRead(value.read)
    if (changed.value.search) snapshot = await capabilitiesApi.saveWebSearch(value.search)
    if (changed.value.network)
      snapshot = await capabilitiesApi.saveNetwork({
        fake_ip_networks: networks.value,
        public_dns_url: value.dns.trim(),
      } satisfies Network)
    if (snapshot) {
      client.setQueryData(keys.host.settings(), snapshot)
      draft.value = pick(snapshot)
    }
    toast.success(t('common.saved'))
  } catch (error) {
    const described = describeError(error, t('ui.error.network'))
    saveError.value = described.message
    saveRawError.value = described.raw
    void settings.refetch()
  } finally {
    void readPendingRestart()
    saving.value = false
  }
}
</script>

<template>
  <Skeleton v-if="settings.isPending.value" :lines="6" />
  <ErrorNote
    v-else-if="settings.isError.value"
    :title="t('capabilities.web.readFailed')"
    :error="settings.error.value"
    :retry="settings.refetch"
  />
  <div v-else-if="draft" class="flex min-w-0 max-w-3xl flex-col gap-4">
    <div class="flex min-w-0 flex-col gap-6">
      <FormSection :title="t('capabilities.web.read')">
        <Field :label="t('capabilities.web.readOn')" inline wide>
          <Switch
            :model-value="draft.read !== null"
            @update:model-value="
              (on: boolean) =>
                (draft!.read = on ? { provider: 'local', connection: null, timeout_seconds: 20 } : null)
            "
          />
        </Field>
        <Field v-if="draft.read" :label="t('capabilities.web.readProvider')">
          <Select v-model="draft.read.provider" :options="readers" />
        </Field>
        <Field
          v-if="draft.read && readKeyed"
          :label="t('capabilities.web.readConnection')"
          required
          :error="readConnectionError"
        >
          <div class="flex flex-wrap items-center gap-2 sm:flex-nowrap">
            <div class="min-w-44 flex-1">
              <Select
                :model-value="draft.read.connection ?? undefined"
                :options="readConnections"
                :disabled="!readConnections.length"
                @update:model-value="(value) => (draft!.read!.connection = value ?? null)"
              />
            </div>
            <Button variant="ghost" size="sm" :to="{ name: 'host-models', query: { tab: 'providers' } }">
              {{ t('capabilities.web.manageConnections') }}
            </Button>
          </div>
        </Field>
        <Field
          v-if="draft.read"
          :label="t('capabilities.web.timeout')"
          :error="draft.read.timeout_seconds === null ? t('capabilities.required') : null"
        >
          <NumberInput
            v-model="draft.read.timeout_seconds"
            :min="1"
            :snap="false"
            :steppers="false"
            :unit="t('capabilities.seconds')"
          />
        </Field>
      </FormSection>
      <FormSection :title="t('capabilities.web.search')">
        <Field :label="t('capabilities.web.searchOn')" inline wide>
          <Switch
            :model-value="draft.search !== null"
            @update:model-value="
              (on: boolean) =>
                (draft!.search = on
                  ? { provider: 'yahoo', connection: null, timeout_seconds: 15, max_results: 5 }
                  : null)
            "
          />
        </Field>
        <template v-if="draft.search">
          <Field :label="t('capabilities.web.provider')">
            <Select v-model="draft.search.provider" :options="providers" />
          </Field>
          <Field
            v-if="searchKeyed"
            :label="t('capabilities.web.connection')"
            required
            :error="searchConnectionError"
          >
            <div class="flex flex-wrap items-center gap-2 sm:flex-nowrap">
              <div class="min-w-44 flex-1">
                <Select
                  :model-value="draft.search.connection ?? undefined"
                  :options="searchConnections"
                  :disabled="!searchConnections.length"
                  @update:model-value="(value) => (draft!.search!.connection = value ?? null)"
                />
              </div>
              <Button variant="ghost" size="sm" :to="{ name: 'host-models', query: { tab: 'providers' } }">
                {{ t('capabilities.web.manageConnections') }}
              </Button>
            </div>
          </Field>
          <Field
            :label="t('capabilities.web.results')"
            :error="draft.search.max_results === null ? t('capabilities.required') : null"
          >
            <NumberInput v-model="draft.search.max_results" :min="1" :max="20" />
          </Field>
          <Field
            :label="t('capabilities.web.timeout')"
            :error="draft.search.timeout_seconds === null ? t('capabilities.required') : null"
          >
            <NumberInput
              v-model="draft.search.timeout_seconds"
              :min="1"
              :snap="false"
              :steppers="false"
              :unit="t('capabilities.seconds')"
            />
          </Field>
        </template>
      </FormSection>
      <FormSection :title="t('capabilities.web.network')">
        <Field :label="t('capabilities.web.fakeIp')">
          <Textarea v-model="draft.fakeIp" :rows="2" mono placeholder="198.18.0.0/15" />
        </Field>
        <Field
          :label="t('capabilities.web.dns')"
          :error="/^https?:\/\/[^/?#]+/.test(draft.dns.trim()) ? null : t('capabilities.web.dnsRule')"
        >
          <Input v-model="draft.dns" type="url" mono />
        </Field>
      </FormSection>
    </div>
    <SaveBar
      :dirty="dirty"
      :saving="saving"
      :error="saveError"
      :raw-error="saveRawError"
      :invalid="invalid"
      @save="save"
      @discard="
        () => {
          draft = initial && copy(initial)
          saveError = null
          saveRawError = null
        }
      "
    />
  </div>
</template>
