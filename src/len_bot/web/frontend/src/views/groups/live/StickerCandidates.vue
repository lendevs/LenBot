<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Badge from '../../../ui/Badge.vue'

interface Candidate {
  number: number
  kind: 'persona' | 'group'
  file?: string
  id?: number
  description: string
}

const props = defineProps<{ result: string; chosen: number | null }>()
const { t } = useI18n()

// The model-visible result is one JSON line, optionally followed by a sentence for the model.
const candidates = computed<Candidate[]>(() => {
  try {
    const value = JSON.parse(props.result.split('\n', 1)[0] ?? '')
    return Array.isArray(value?.candidates) ? value.candidates : []
  } catch {
    return []
  }
})
const source = (item: Candidate) =>
  item.kind === 'persona'
    ? t('groups.live.step.candidateSource.persona', { file: item.file })
    : t('groups.live.step.candidateSource.group', { id: item.id })
</script>

<template>
  <section v-if="candidates.length" class="flex flex-col gap-1">
    <p class="text-xs font-medium text-muted">{{ t('groups.live.step.candidates') }}</p>
    <ol class="flex list-none flex-col gap-1">
      <li
        v-for="item in candidates"
        :key="item.number"
        class="flex flex-wrap items-baseline gap-x-2 text-sm"
        :class="item.number === chosen ? 'text-ink' : 'text-ink-2'"
      >
        <span class="font-mono text-xs text-subtle tabular">{{ item.number }}</span>
        <span class="font-mono text-xs">{{ source(item) }}</span>
        <span class="break-words">{{ item.description }}</span>
        <Badge v-if="item.number === chosen" tone="success">{{ t('groups.live.step.candidateSent') }}</Badge>
      </li>
    </ol>
  </section>
</template>
