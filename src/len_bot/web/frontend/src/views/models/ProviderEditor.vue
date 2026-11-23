<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, Eye, EyeOff, Trash2 } from '@lucide/vue'
import Button from '../../ui/Button.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import IconButton from '../../ui/IconButton.vue'
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
const reveal = ref(false)
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
const keyReentryNeeded = computed(
  () => row.value.keyConfigured && !keyReusable(row.value) && !row.value.api_key.trim(),
)
const keyError = computed(() =>
  keyReentryNeeded.value
    ? (errorOf('key') ??
      t('models.problems.keyAgain', { name: row.value.alias || t('models.providers.unnamed') }))
    : row.value.keyConfigured
      ? errorOf('key')
      : undefined,
)
/** Search and read services have no model to test. */
const WEB_ONLY = Object.values(SERVICE_PROVIDER).map((item) => item.api)
</script>

<template>
  <section class="flex min-w-0 max-w-3xl flex-col gap-6">
    <div class="flex min-w-0 items-center justify-between gap-3 border-b border-line pb-3">
      <span v-if="!wide" class="-ml-2 inline-flex">
        <Button variant="ghost" size="sm" :icon="ArrowLeft" @click="emit('back')">
          {{ t('models.providers.title') }}
        </Button>
      </span>
      <h3 v-else class="min-w-0 flex-1 truncate text-lg font-semibold text-ink">
        {{ row.alias || t('models.providers.unnamed') }}
      </h3>
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
      <Field :label="t('models.providers.key')" required :error="keyError">
        <Input
          v-model="row.api_key"
          :type="reveal ? 'text' : 'password'"
          mono
          autocomplete="new-password"
          :placeholder="
            keyReusable(row)
              ? t('models.providers.keyKept')
              : keyReentryNeeded
                ? t('models.providers.keyReenter')
                : undefined
          "
        >
          <template #suffix>
            <span class="-mr-2 inline-flex">
              <IconButton
                :icon="reveal ? EyeOff : Eye"
                :label="reveal ? t('ui.secret.hide') : t('ui.secret.show')"
                variant="ghost"
                size="sm"
                @click="reveal = !reveal"
              />
            </span>
          </template>
        </Input>
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
    <div v-if="!WEB_ONLY.includes(row.api)" class="flex flex-col gap-3.5 border-t border-line pt-6">
      <h4 class="text-sm font-semibold text-ink">{{ t('models.probe.title') }}</h4>
      <ProbeTools :row="row" />
    </div>
  </section>
</template>
