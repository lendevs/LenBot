<script setup lang="ts">
import { computed } from 'vue'
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
const apiOptions = computed(() =>
  (form.protocols.data.value?.protocols ?? []).map((item) => ({
    value: item.api,
    label: protocolTitle(item),
  })),
)
const errorOf = (field: 'name' | 'url' | 'key') =>
  form.problems.value.find((item) => item.provider === props.id && item.field === field)?.text
/** Search and read services have no model to test. */
const WEB_ONLY = Object.values(SERVICE_PROVIDER).map((item) => item.api)
</script>

<template>
  <section class="flex min-w-0 flex-col gap-5 rounded-xl border border-line bg-surface p-5">
    <div class="flex min-w-0 items-center gap-2">
      <Button v-if="!wide" variant="ghost" size="sm" :icon="ArrowLeft" class="-ml-2" @click="emit('back')">
        {{ t('models.providers.title') }}
      </Button>
      <h3 v-else class="min-w-0 flex-1 truncate text-base font-semibold">
        {{ row.alias || t('models.providers.unnamed') }}
      </h3>
      <span v-if="!wide" class="flex-1" />
      <Button variant="danger-ghost" size="sm" :icon="Trash2" @click="emit('remove')">
        {{ t('common.delete') }}
      </Button>
    </div>
    <div class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
      <Field :label="t('models.providers.name')" required :error="errorOf('name')">
        <Input v-model="row.alias" />
      </Field>
      <Field :label="t('models.providers.api')">
        <Select
          :model-value="row.api"
          :options="apiOptions"
          @update:model-value="(api) => api && form.changeProtocol(row, api)"
        />
      </Field>
      <Field :label="t('models.providers.url')" required wide :error="errorOf('url')">
        <Input v-model="row.base_url" type="url" mono placeholder="https://api.example.com/v1" />
      </Field>
      <Field
        :label="t('models.providers.key')"
        required
        :error="row.keyConfigured ? errorOf('key') : undefined"
      >
        <Input
          v-model="row.api_key"
          type="password"
          mono
          autocomplete="new-password"
          :placeholder="keyReusable(row) ? t('models.providers.keyKept') : undefined"
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
    <div v-if="!WEB_ONLY.includes(row.api)" class="flex flex-col gap-3 border-t border-line pt-5">
      <h4 class="text-sm font-semibold">{{ t('models.probe.title') }}</h4>
      <ProbeTools :row="row" />
    </div>
  </section>
</template>
