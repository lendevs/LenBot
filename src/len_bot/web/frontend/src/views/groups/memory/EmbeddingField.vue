<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { List, Zap } from '@lucide/vue'
import { modelsApi, type EmbeddingBinding, type SavedProvider } from '../../../api/models'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import Select from '../../../ui/Select.vue'
import Switch from '../../../ui/Switch.vue'

/** An embedding model on one of the saved providers; null means full-text search only. */
const binding = defineModel<EmbeddingBinding | null>({ required: true })
const props = defineProps<{ providers: Record<string, SavedProvider> }>()

const { t } = useI18n()
const aliases = computed(() => Object.keys(props.providers))
const enabled = computed({
  get: () => binding.value !== null,
  set: (on: boolean) => (binding.value = on ? { provider: aliases.value[0] ?? '', model: '', dimensions: null } : null),
})
const providerOptions = computed(() => aliases.value.map((alias) => ({ value: alias, label: alias })))
const provider = computed(() => (binding.value ? props.providers[binding.value.provider] : undefined))

const list = useMutation({ mutationFn: () => modelsApi.list(binding.value!.provider, provider.value!) })
const probe = useMutation({
  mutationFn: () => modelsApi.probeEmbedding(binding.value!.provider, provider.value!, binding.value!),
})
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
const listed = computed(() =>
  (list.data.value?.models ?? []).map((item) => ({
    value: item.id,
    label: item.name && item.name !== item.id ? `${item.name} · ${item.id}` : item.id,
  })),
)
const picked = ref<string>()
watch(picked, (id) => {
  if (id && binding.value) binding.value.model = id
})
</script>

<template>
  <div class="flex flex-col gap-4">
    <Field :label="t('groups.memory.settings.embedding')" inline>
      <Switch v-model="enabled" />
    </Field>
    <template v-if="binding">
      <div class="grid gap-4 sm:grid-cols-2">
        <Field :label="t('groups.memory.settings.provider')">
          <Select v-model="binding.provider" :options="providerOptions" :placeholder="t('groups.memory.settings.noProvider')" />
        </Field>
        <Field :label="t('groups.memory.settings.model')">
          <Input v-model="binding.model" mono />
        </Field>
        <Field :label="t('groups.memory.settings.dimensions')">
          <NumberInput v-model="binding.dimensions" :min="1" :steppers="false" :placeholder="t('groups.memory.index.defaultDimensions')" />
        </Field>
        <Field v-if="listed.length" :label="t('groups.memory.settings.pick')">
          <Select v-model="picked" :options="listed" />
        </Field>
      </div>
      <div v-if="provider" class="flex flex-wrap gap-2">
        <Button size="sm" :icon="List" :loading="list.isPending.value" @click="list.mutate()">
          {{ t('groups.memory.settings.list') }}
        </Button>
        <Button size="sm" :icon="Zap" :loading="probe.isPending.value" :disabled="!binding.model.trim()" @click="probe.mutate()">
          {{ t('groups.memory.settings.probe') }}
        </Button>
      </div>
      <p v-if="list.isSuccess.value" class="text-xs text-muted">
        {{ t('groups.memory.settings.listed', { n: list.data.value?.models.length ?? 0 }) }}
      </p>
      <ErrorNote v-if="list.isError.value" :title="t('groups.memory.settings.listFailed')" :error="list.error.value" />
      <ErrorNote v-if="probe.isError.value" :title="t('groups.memory.settings.probeFailed')" :error="probe.error.value" />
      <p v-if="probe.data.value" role="status" class="rounded-md bg-success-bg px-3 py-2 text-sm whitespace-pre-wrap text-success">
        {{ probe.data.value.text }}
      </p>
    </template>
  </div>
</template>
