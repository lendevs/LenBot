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
import { keys } from '../../api/query'
import { settingsApi, type SettingsSnapshot } from '../../api/settings'
import { useUnsavedChanges } from '../../composables/useUnsavedChanges'
import { readPendingRestart } from '../../api/hostStore'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import FormSection from '../../ui/FormSection.vue'
import Input from '../../ui/Input.vue'
import NumberInput from '../../ui/NumberInput.vue'
import SaveBar from '../../ui/SaveBar.vue'
import Select from '../../ui/Select.vue'
import Skeleton from '../../ui/Skeleton.vue'
import Switch from '../../ui/Switch.vue'
import Textarea from '../../ui/Textarea.vue'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

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
const providers: { value: WebSearch['provider']; label: string }[] = [
  { value: 'yahoo', label: 'Yahoo' },
  { value: 'bing_rss', label: 'Bing RSS' },
]
const dirty = computed(() => Object.values(changed.value).some(Boolean))
useUnsavedChanges(dirty, { keep: ['tab'] })
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
    (value.read !== null && value.read.timeout_seconds === null) ||
    (value.search !== null && (value.search.timeout_seconds === null || value.search.max_results === null)) ||
    !/^https?:\/\/[^/?#]+/.test(value.dns.trim())
  )
})

const saving = ref(false)
const saveError = ref<string | null>(null)
async function save() {
  const value = draft.value!
  saving.value = true
  saveError.value = null
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
    void readPendingRestart()
    toast.success(t('common.saved'))
  } catch (error) {
    saveError.value = describeError(error, t('ui.error.network')).message
    void settings.refetch()
  } finally {
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
  <div v-else-if="draft" class="flex min-w-0 flex-col gap-4">
    <div class="flex min-w-0 flex-col gap-6 rounded-xl border border-line bg-surface p-5">
      <FormSection :title="t('capabilities.web.read')">
        <Field :label="t('capabilities.web.readOn')" inline wide>
          <Switch
            :model-value="draft.read !== null"
            @update:model-value="(on: boolean) => (draft!.read = on ? { timeout_seconds: 20 } : null)"
          />
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
                (draft!.search = on ? { provider: 'yahoo', timeout_seconds: 15, max_results: 5 } : null)
            "
          />
        </Field>
        <template v-if="draft.search">
          <Field :label="t('capabilities.web.provider')">
            <Select v-model="draft.search.provider" :options="providers" />
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
      :invalid="invalid"
      @save="save"
      @discard="draft = initial && copy(initial)"
    />
  </div>
</template>
