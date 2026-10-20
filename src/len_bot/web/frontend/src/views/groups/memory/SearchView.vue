<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { FileText, Search } from '@lucide/vue'
import { memoryApi, type MemoryScope } from '../../../api/memory'
import { developerDetails } from '../../../composables/useDeveloperMode.js'
import { formatNumber } from '../../../i18n/format'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Input from '../../../ui/Input.vue'

const props = defineProps<{ scene: string }>()
const emit = defineEmits<{ open: [hit: { scope: MemoryScope; path: string }] }>()

const { t } = useI18n()
const text = ref('')
const search = useMutation({ mutationFn: (query: string) => memoryApi.search(props.scene, query) })
function submit() {
  const query = text.value.trim()
  if (query) search.mutate(query)
}
</script>

<template>
  <div class="flex max-w-3xl flex-col gap-4">
    <form class="flex gap-2" @submit.prevent="submit">
      <Input
        v-model="text"
        :icon="Search"
        :placeholder="t('groups.memory.search.placeholder')"
        :aria-label="t('groups.memory.search.placeholder')"
        class="flex-1"
      />
      <Button type="submit" variant="primary" :loading="search.isPending.value" :disabled="!text.trim()">
        {{ t('common.search') }}
      </Button>
    </form>
    <ErrorNote v-if="search.isError.value" :title="t('groups.memory.search.failed')" :error="search.error.value" />
    <EmptyState v-else-if="search.data.value && !search.data.value.hits.length" :title="t('groups.memory.search.none')" compact />
    <ul v-else-if="search.data.value" class="flex list-none flex-col divide-y divide-line border-y border-line">
      <li v-for="hit in search.data.value.hits" :key="`${hit.scope}:${hit.path}`">
        <button
          type="button"
          class="flex w-full cursor-pointer flex-col gap-1.5 px-1 py-3 text-left hover:bg-hover focus-visible:focus-ring"
          @click="emit('open', { scope: hit.scope, path: hit.path })"
        >
          <span class="flex min-w-0 items-center gap-2">
            <FileText :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
            <Badge v-if="hit.scope === 'public'">{{ t('groups.memory.scopes.public') }}</Badge>
            <span class="min-w-0 truncate font-mono text-sm text-ink">{{ hit.path }}</span>
            <span v-if="developerDetails" class="ml-auto shrink-0 text-xs text-subtle tabular">
              {{ hit.score === null ? '—' : formatNumber(hit.score, { maximumFractionDigits: 3 }) }}
              · {{ hit.total_chars === null ? '—' : t('groups.memory.search.chars', { n: hit.total_chars }) }}
            </span>
          </span>
          <span class="line-clamp-3 text-sm break-words whitespace-pre-wrap text-ink-2">{{ hit.preview }}</span>
        </button>
      </li>
    </ul>
  </div>
</template>
