<script setup lang="ts">
import { computed, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, Trash2 } from '@lucide/vue'
import Button from '../../ui/Button.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import Input from '../../ui/Input.vue'
import Select from '../../ui/Select.vue'
import ProbeTools from './ProbeTools.vue'
import { SERVICE_PROVIDER } from '../../api/webServices'
import { keyReusable, useForm, type ProviderRow } from './form'
import { useProtocolTitle } from './protocols'

const props = defineProps<{ id: string; wide: boolean }>()
const emit = defineEmits<{ back: []; remove: [] }>()

const { t } = useI18n()
const form = useForm()
const protocolTitle = useProtocolTitle()
// Edited in place: the row belongs to the form's draft.
const row = computed(() => form.providerFor(props.id) as ProviderRow)
const isNew = computed(() => row.value.originalAlias === null)
const touched = reactive({ name: false, url: false, key: false })
const apiOptions = computed(() =>
  (form.protocols.data.value?.protocols ?? []).map((item) => ({
    value: item.api,
    label: protocolTitle(item),
  })),
)
const errorOf = (field: 'name' | 'url' | 'key') =>
  form.problems.value.find((item) => item.provider === props.id && item.field === field)?.text
const webProtocolError = computed(
  () =>
    form.problems.value.find(
      (item) => item.provider === props.id && (item.place === 'web_search' || item.place === 'web_read'),
    )?.text,
)
const nameError = computed(() =>
  !isNew.value || touched.name || Boolean(row.value.alias) || form.triedSave.value
    ? errorOf('name')
    : undefined,
)
const urlError = computed(() =>
  !isNew.value || touched.url || form.triedSave.value ? errorOf('url') : undefined,
)
const keyReentryNeeded = computed(
  () => row.value.keyConfigured && !keyReusable(row.value) && !row.value.api_key.trim(),
)
const keyError = computed(() =>
  keyReentryNeeded.value
    ? (errorOf('key') ??
      t('models.problems.keyAgain', { name: row.value.alias || t('models.providers.unnamed') }))
    : !isNew.value ||
        touched.key ||
        form.triedSave.value ||
        (Boolean(row.value.alias.trim()) && Boolean(row.value.base_url.trim()))
      ? errorOf('key')
      : undefined,
)
/** Search, read and audio-transcription protocols have no text/embedding probe here. */
const NO_PROBE = [...Object.values(SERVICE_PROVIDER).map((item) => item.api), 'openai-audio']
</script>

<template>
  <section class="flex min-w-0 max-w-3xl flex-col gap-6">
    <div class="flex min-w-0 items-center justify-between gap-2 border-b border-line pb-3">
      <span v-if="!wide" class="-ml-2 inline-flex shrink-0">
        <Button variant="ghost" size="sm" :icon="ArrowLeft" @click="emit('back')">
          {{ t('common.back') }}
        </Button>
      </span>
      <h3 class="min-w-0 flex-1 truncate text-base font-semibold text-ink lg:text-lg">
        {{ row.alias || t('models.providers.unnamed') }}
      </h3>
      <Button variant="danger-ghost" size="sm" class="shrink-0" :icon="Trash2" @click="emit('remove')">
        {{ t('common.delete') }}
      </Button>
    </div>
    <div class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
      <Field :label="t('models.providers.name')" required :error="nameError">
        <Input v-model="row.alias" @blur="touched.name = true" />
      </Field>
      <Field :label="t('models.providers.api')" :error="webProtocolError">
        <Select
          :model-value="row.api"
          :options="apiOptions"
          @update:model-value="(api) => api && form.changeProtocol(row, api)"
        />
      </Field>
      <Field :label="t('models.providers.url')" required wide :error="urlError">
        <Input
          v-model="row.base_url"
          type="url"
          mono
          placeholder="https://api.example.com/v1"
          @blur="touched.url = true"
        />
      </Field>
      <Field :label="t('models.providers.key')" required :error="keyError">
        <Input
          v-model="row.api_key"
          type="password"
          mono
          autocomplete="new-password"
          :placeholder="
            keyReusable(row)
              ? t('models.providers.keyKept')
              : keyReentryNeeded
                ? t('models.providers.keyReenter')
                : undefined
          "
          @blur="touched.key = true"
        />
      </Field>
      <Field :label="t('models.providers.proxy')">
        <Input v-model="row.proxy" type="url" mono placeholder="http://127.0.0.1:7890" />
      </Field>
    </div>
    <ErrorNote
      v-if="form.protocols.isError.value"
      :title="t('models.protocolsFailed')"
      :error="form.protocols.error.value"
      :retry="form.protocols.refetch"
    />
    <div v-if="!NO_PROBE.includes(row.api)" class="flex flex-col gap-3.5 border-t border-line pt-6">
      <h4 class="text-sm font-semibold text-ink">{{ t('models.probe.title') }}</h4>
      <ProbeTools :row="row" />
    </div>
  </section>
</template>
