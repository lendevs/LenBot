<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { FileText, Search } from '@lucide/vue'
import { memoryApi, type MemoryScope } from '../../../api/memory'
import { developerDetails } from '../../../composables/useDeveloperMode'
import { formatNumber } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Input from '../../../ui/Input.vue'

defineOptions({ name: 'SearchView' })

const props = defineProps<{ scene: string; retrieval?: string | null }>()
const emit = defineEmits<{ open: [hit: { scope: MemoryScope; path: string }] }>()

const { t } = useI18n()
const text = ref('')
const search = useMutation({ mutationFn: (query: string) => memoryApi.search(props.scene, query) })
watch(
  () => props.scene,
  () => {
    text.value = ''
    search.reset()
  },
)
function submit() {
  const query = text.value.trim()
  if (query) search.mutate(query)
}

function highlightParts(preview: string, query: string): { text: string; match: boolean }[] {
  const terms = [...new Set(query.trim().split(/\s+/).filter(Boolean))].sort((a, b) => b.length - a.length)
  if (!terms.length || !preview) return [{ text: preview, match: false }]
  const pattern = new RegExp(
    `(${terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`,
    'gi',
  )
  const parts: { text: string; match: boolean }[] = []
  let last = 0
  for (const found of preview.matchAll(pattern)) {
    const start = found.index ?? 0
    if (start > last) parts.push({ text: preview.slice(last, start), match: false })
    parts.push({ text: found[0], match: true })
    last = start + found[0].length
  }
  if (last < preview.length) parts.push({ text: preview.slice(last), match: false })
  return parts.length ? parts : [{ text: preview, match: false }]
}
</script>

<template>
  <div class="flex max-w-3xl min-w-0 flex-col gap-4">
    <form class="flex gap-2" @submit.prevent="submit">
      <div class="min-w-0 flex-1">
        <Input
          v-model="text"
          :icon="Search"
          :placeholder="t('groups.memory.search.placeholder')"
          :aria-label="t('groups.memory.search.placeholder')"
          clearable
        />
      </div>
      <Button type="submit" variant="primary" :loading="search.isPending.value" :disabled="!text.trim()">
        {{ t('common.search') }}
      </Button>
    </form>
    <div v-if="retrieval" class="flex items-center gap-2 text-xs text-muted">
      <span>{{ t('groups.memory.index.retrieval') }}</span>
      <Badge :tone="retrieval === 'hybrid' ? 'success' : 'neutral'">
        {{ retrieval === 'hybrid' ? t('groups.memory.index.hybrid') : t('groups.memory.index.fulltext') }}
      </Badge>
    </div>
    <ErrorNote
      v-if="search.isError.value"
      :title="t('groups.memory.search.failed')"
      :error="search.error.value"
    />
    <EmptyState
      v-else-if="search.data.value && !search.data.value.hits.length"
      :title="t('groups.memory.search.none')"
      compact
    />
    <ul
      v-else-if="search.data.value"
      class="flex list-none flex-col divide-y divide-line border-y border-line"
    >
      <li v-for="hit in search.data.value.hits" :key="`${hit.scope}:${hit.path}`">
        <button
          type="button"
          class="flex w-full cursor-pointer flex-col gap-1.5 px-2 py-3.5 text-left transition-colors duration-150 hover:bg-hover focus-visible:focus-ring"
          @click="emit('open', { scope: hit.scope, path: hit.path })"
        >
          <span class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <FileText :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
            <Badge v-if="hit.scope === 'public'">{{ t('groups.memory.scopes.public') }}</Badge>
            <span class="min-w-0 flex-1 truncate font-mono text-sm font-medium text-ink">{{ hit.path }}</span>
            <span v-if="developerDetails" class="ml-auto shrink-0 text-xs text-subtle tabular">
              {{ hit.score === null ? '—' : formatNumber(hit.score, { maximumFractionDigits: 3 }) }}
              ·
              {{
                hit.total_chars === null
                  ? '—'
                  : t('groups.memory.search.chars', { n: formatNumber(hit.total_chars) })
              }}
            </span>
          </span>
          <span class="line-clamp-3 text-sm leading-6 break-words whitespace-pre-wrap text-ink-2">
            <template
              v-for="(part, idx) in highlightParts(hit.preview, search.variables.value ?? '')"
              :key="idx"
            >
              <mark v-if="part.match" class="rounded-xs bg-selected px-0.5 text-ink">{{ part.text }}</mark>
              <template v-else>{{ part.text }}</template>
            </template>
          </span>
        </button>
      </li>
    </ul>
  </div>
</template>
