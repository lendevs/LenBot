<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpRight } from '@lucide/vue'
import { groupLabel, sceneSecondaryId } from '../../layouts/shell/scenes'
import Button from '../../ui/Button.vue'
import { groupsTarget } from '../groups/route'
import EmbeddingField from '../groups/memory/EmbeddingField.vue'
import { candidateOf, hasKey, useForm, type ProblemField } from './form'

const { t } = useI18n()
const form = useForm()
const providers = computed(() =>
  (form.draft.value?.providers ?? [])
    .filter((row) => form.supports(row, 'embedding'))
    .map((row) => ({
      id: row.id,
      label: row.alias || t('models.providers.unnamed'),
      candidate: hasKey(row) && row.base_url.trim() ? candidateOf(row) : null,
    })),
)
const learning = computed(() => Object.keys(form.draft.value?.learning_embeddings ?? {}))
const fieldError = (place: string, field: ProblemField) =>
  form.problems.value.find((item) => item.place === place && item.field === field)?.text
</script>

<template>
  <div class="flex min-w-0 max-w-3xl flex-col divide-y divide-line">
    <section class="flex min-w-0 flex-col gap-4 py-6 first:pt-1">
      <h3 class="text-base font-semibold text-ink">{{ t('models.vectors.memory') }}</h3>
      <template v-if="form.memoryOn.value">
        <EmbeddingField
          v-model="form.draft.value!.memory_embedding"
          :providers="providers"
          :label="t('models.vectors.use')"
          :provider-error="fieldError('memory', 'provider')"
          :model-error="fieldError('memory', 'model')"
        />
      </template>
      <div v-else class="flex flex-wrap items-center justify-between gap-2">
        <p class="text-sm text-muted">{{ t('models.vectors.memoryOff') }}</p>
        <Button
          size="sm"
          variant="ghost"
          :icon-right="ArrowUpRight"
          :to="groupsTarget(undefined, 'memory', { tab: 'settings' })"
        >
          {{ t('models.vectors.openMemorySettings') }}
        </Button>
      </div>
    </section>
    <section class="flex min-w-0 flex-col gap-4 py-6 last:pb-0">
      <h3 class="text-base font-semibold text-ink">{{ t('models.vectors.learning') }}</h3>
      <p v-if="!learning.length" class="text-sm text-muted">{{ t('models.vectors.learningOff') }}</p>
      <div v-else class="flex flex-col divide-y divide-line">
        <div v-for="scene in learning" :key="scene" class="flex flex-col gap-3 py-5 first:pt-1 last:pb-0">
          <div class="flex min-w-0 items-baseline gap-2">
            <span class="min-w-0 truncate text-sm font-semibold text-ink">{{ groupLabel(scene) }}</span>
            <span
              v-if="sceneSecondaryId(scene)"
              class="max-w-28 shrink-0 truncate font-mono text-xs text-muted tabular sm:max-w-none"
            >
              {{ sceneSecondaryId(scene) }}
            </span>
          </div>
          <EmbeddingField
            v-model="form.draft.value!.learning_embeddings[scene]"
            :providers="providers"
            :label="t('models.vectors.use')"
            :provider-error="fieldError(`learning.${scene}`, 'provider')"
            :model-error="fieldError(`learning.${scene}`, 'model')"
          />
        </div>
      </div>
    </section>
  </div>
</template>
