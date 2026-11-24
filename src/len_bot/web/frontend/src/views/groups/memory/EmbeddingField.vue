<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { List, Zap } from '@lucide/vue'
import { modelsApi, type Candidate, type EmbeddingBinding } from '../../../api/models'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import Select from '../../../ui/Select.vue'
import Switch from '../../../ui/Switch.vue'
import ModelName from '../../models/ModelName.vue'

export interface EmbeddingProvider {
  /** What `binding.provider` holds. */
  id: string
  label: string
  /** How to reach the provider for listing and testing; null while its key is missing. */
  candidate: Candidate | null
}

/** An embedding model on one of the providers; null means full-text search only. */
const binding = defineModel<EmbeddingBinding | null>({ required: true })
const props = withDefaults(
  defineProps<{
    providers: EmbeddingProvider[]
    label?: string
    providerError?: string
    modelError?: string
  }>(),
  {
    label: undefined,
    providerError: undefined,
    modelError: undefined,
  },
)

const { t } = useI18n()
const enabled = computed({
  get: () => binding.value !== null,
  set: (on: boolean) =>
    (binding.value = on ? { provider: props.providers[0]?.id ?? '', model: '', dimensions: null } : null),
})
const providerOptions = computed(() => props.providers.map((item) => ({ value: item.id, label: item.label })))
const provider = computed(() => props.providers.find((item) => item.id === binding.value?.provider))

const list = useMutation({ mutationFn: () => modelsApi.list(provider.value!.candidate!) })
const probe = useMutation({
  mutationFn: () => modelsApi.probe(provider.value!.candidate!, binding.value!, 'embedding'),
})
const listedCount = computed(() => list.data.value?.models.length ?? 0)
watch(
  () => binding.value?.provider,
  () => {
    list.reset()
    probe.reset()
  },
)
watch(
  () => JSON.stringify(binding.value),
  () => probe.reset(),
)
</script>

<template>
  <div class="flex flex-col gap-4">
    <Field :label="label ?? t('groups.memory.settings.embedding')" inline>
      <Switch v-model="enabled" />
    </Field>
    <template v-if="binding">
      <div class="grid gap-4 sm:grid-cols-2">
        <Field :label="t('groups.memory.settings.provider')" :error="providerError">
          <Select
            v-model="binding.provider"
            :options="providerOptions"
            :placeholder="t('groups.memory.settings.noProvider')"
          />
        </Field>
        <Field :label="t('groups.memory.settings.model')" :error="modelError">
          <ModelName
            v-model="binding.model"
            :models="list.data.value?.models"
            can-refresh
            :refresh-disabled="!provider?.candidate"
            :refreshing="list.isPending.value"
            @refresh="provider?.candidate && list.mutate()"
          />
        </Field>
        <Field :label="t('groups.memory.settings.dimensions')">
          <NumberInput
            v-model="binding.dimensions"
            :min="1"
            :steppers="false"
            :placeholder="t('groups.memory.index.defaultDimensions')"
          />
        </Field>
      </div>
      <div v-if="provider?.candidate" class="flex flex-wrap items-center gap-2">
        <Button size="sm" :icon="List" :loading="list.isPending.value" @click="list.mutate()">
          {{ t('groups.memory.settings.list') }}
        </Button>
        <Button
          size="sm"
          :icon="Zap"
          :loading="probe.isPending.value"
          :disabled="!binding.model.trim()"
          @click="probe.mutate()"
        >
          {{ t('groups.memory.settings.probe') }}
        </Button>
        <span v-if="list.isSuccess.value" class="text-xs text-muted tabular">
          {{ t('groups.memory.settings.listed', { n: listedCount }, listedCount) }}
        </span>
      </div>
      <ErrorNote
        v-if="list.isError.value"
        :title="t('groups.memory.settings.listFailed')"
        :error="list.error.value"
      />
      <ErrorNote
        v-if="probe.isError.value"
        :title="t('groups.memory.settings.probeFailed')"
        :error="probe.error.value"
      />
      <p
        v-if="probe.data.value"
        role="status"
        class="animate-fade rounded-lg bg-success-bg px-3.5 py-2.5 text-sm break-words whitespace-pre-wrap text-success"
      >
        {{ probe.data.value.text }}
      </p>
    </template>
  </div>
</template>
