<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { groupLabel } from '../../layouts/shell/scenes'
import EmbeddingField from '../groups/memory/EmbeddingField.vue'
import { candidateOf, hasKey, sceneSecondaryId, useForm } from './form'

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
const errorsAt = (place: string) => form.problems.value.filter((item) => item.place === place)
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
        />
        <p v-for="item in errorsAt('memory')" :key="item.text" class="text-sm text-error">{{ item.text }}</p>
      </template>
      <p v-else class="text-sm text-muted">{{ t('models.vectors.memoryOff') }}</p>
    </section>
    <section class="flex min-w-0 flex-col gap-4 py-6 last:pb-0">
      <h3 class="text-base font-semibold text-ink">{{ t('models.vectors.learning') }}</h3>
      <p v-if="!learning.length" class="text-sm text-muted">{{ t('models.vectors.learningOff') }}</p>
      <div v-else class="flex flex-col divide-y divide-line">
        <div v-for="scene in learning" :key="scene" class="flex flex-col gap-3 py-5 first:pt-1 last:pb-0">
          <div class="flex min-w-0 items-baseline gap-2">
            <span class="truncate text-sm font-semibold text-ink">{{ groupLabel(scene) }}</span>
            <span v-if="sceneSecondaryId(scene)" class="shrink-0 font-mono text-xs text-muted tabular">
              {{ sceneSecondaryId(scene) }}
            </span>
          </div>
          <EmbeddingField
            v-model="form.draft.value!.learning_embeddings[scene]"
            :providers="providers"
            :label="t('models.vectors.use')"
          />
          <p v-for="item in errorsAt(`learning.${scene}`)" :key="item.text" class="text-sm text-error">
            {{ item.text }}
          </p>
        </div>
      </div>
    </section>
  </div>
</template>
