<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ImageOff } from '@lucide/vue'
import { learningApi } from '../../../api/learning'
import { personasApi } from '../../../api/personas'
import Badge from '../../../ui/Badge.vue'

interface Candidate {
  number: number
  kind: 'persona' | 'group'
  file?: string
  id?: number
  description: string
}

const props = defineProps<{
  result: string
  chosen: number | null
  scene?: string
  personaKey?: string
  personaDirectory?: string
}>()
const { t } = useI18n()

const broken = ref(new Set<number>())
watch(
  () => props.result,
  () => {
    broken.value = new Set()
  },
)
function markBroken(number: number) {
  if (broken.value.has(number)) return
  const next = new Set(broken.value)
  next.add(number)
  broken.value = next
}

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

function thumbnail(item: Candidate): string | null {
  if (item.kind === 'group' && props.scene && typeof item.id === 'number') {
    return learningApi.stickerImage(props.scene, item.id)
  }
  if (item.kind === 'persona' && props.personaKey && props.personaDirectory && item.file) {
    return personasApi.stickerImage(props.personaKey, props.personaDirectory, item.file)
  }
  return null
}
</script>

<template>
  <section v-if="candidates.length" class="flex flex-col gap-1.5">
    <p class="text-xs font-medium text-muted">{{ t('groups.live.step.candidates') }}</p>
    <ol class="flex list-none flex-col divide-y divide-line border-y border-line">
      <li
        v-for="item in candidates"
        :key="item.number"
        class="flex items-center gap-2.5 py-1.5 text-sm"
        :class="item.number === chosen ? 'text-ink' : 'text-ink-2'"
      >
        <div
          v-if="thumbnail(item)"
          class="grid size-10 shrink-0 place-items-center overflow-hidden rounded-md border border-line bg-fill p-0.5"
        >
          <ImageOff v-if="broken.has(item.number)" :size="15" class="text-subtle" aria-hidden="true" />
          <img
            v-else
            :src="thumbnail(item)!"
            :alt="item.description || source(item)"
            loading="lazy"
            class="size-full object-contain"
            @error="markBroken(item.number)"
          />
        </div>
        <div class="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span class="font-mono text-xs font-medium text-subtle tabular">#{{ item.number }}</span>
          <span class="font-mono text-xs text-muted tabular">{{ source(item) }}</span>
          <span class="min-w-0 flex-1 break-words">{{ item.description }}</span>
        </div>
        <Badge v-if="item.number === chosen" tone="success">{{ t('groups.live.step.candidateSent') }}</Badge>
      </li>
    </ol>
  </section>
</template>
