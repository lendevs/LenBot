<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useInfiniteQuery } from '@tanstack/vue-query'
import { memoryApi, type MemoryScope } from '../../../api/memory'
import { keys } from '../../../api/query'
import { formatDateTime } from '../../../i18n/format'
import Button from '../../../ui/Button.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'

/** Developer view of the embedding requests memory made, read on demand. */
const props = defineProps<{ scene: string; timeZone: string }>()

const { t, te } = useI18n()
const scope = ref<MemoryScope>('scene')
const scopes = computed(() =>
  (['scene', 'public'] as const).map((value) => ({ value, label: t(`groups.memory.scopes.${value}`) })),
)
const reading = ref(false)
const calls = useInfiniteQuery({
  queryKey: computed(() => keys.memory.embeddingCalls(props.scene, scope.value)),
  queryFn: ({ pageParam, signal }) => memoryApi.embeddingCalls(props.scene, scope.value, pageParam, signal),
  initialPageParam: {} as { offset?: number; snapshot?: number },
  getNextPageParam: (page) =>
    page.next_offset === null ? undefined : { offset: page.next_offset, snapshot: page.snapshot },
  enabled: reading,
})
const rows = computed(() => calls.data.value?.pages.flatMap((page) => page.calls) ?? [])
const opened = ref<Record<number, unknown>>({})
async function detail(id: number) {
  opened.value = { ...opened.value, [id]: await memoryApi.embeddingCall(props.scene, scope.value, id) }
}
const purpose = (value: string) =>
  te(`groups.memory.embedding.purposes.${value}`) ? t(`groups.memory.embedding.purposes.${value}`) : value
</script>

<template>
  <section class="flex flex-col gap-3 border-t border-line pt-6">
    <header class="flex flex-wrap items-center gap-2">
      <h3 class="mr-auto text-base font-semibold text-ink">{{ t('groups.memory.embedding.title') }}</h3>
      <SegmentedControl v-model="scope" :options="scopes" size="sm" :label="t('groups.memory.scope')" />
      <Button size="sm" :loading="calls.isFetching.value" @click="reading ? calls.refetch() : (reading = true)">
        {{ t('groups.memory.embedding.read') }}
      </Button>
    </header>
    <ErrorNote v-if="calls.isError.value" :title="t('groups.memory.readFailed')" :error="calls.error.value" />
    <p v-if="reading && calls.isSuccess.value && !rows.length" class="text-sm text-muted">{{ t('groups.memory.embedding.none') }}</p>
    <ul class="flex list-none flex-col divide-y divide-line">
      <li v-for="call in rows" :key="call.id" class="flex flex-col gap-2 py-3">
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <strong class="font-medium text-ink">#{{ call.id }} {{ purpose(call.purpose) }}</strong>
          <span class="text-xs text-subtle tabular">{{ formatDateTime(call.started, { timeZone }) }}</span>
          <span class="text-xs text-subtle">
            {{ call.tokens ? t('groups.memory.embedding.tokens', { n: call.tokens.input }) : t('groups.memory.embedding.noTokens') }}
          </span>
          <span v-if="call.error" class="text-xs text-error">{{ t('groups.memory.embedding.error') }}</span>
          <Button v-if="!opened[call.id]" size="sm" variant="ghost" class="ml-auto" @click="detail(call.id)">
            {{ t('groups.memory.embedding.detail') }}
          </Button>
        </div>
        <CodeBlock :code="opened[call.id] ?? { usage: call.usage, response: call.response, error: call.error }" :max-lines="10" />
      </li>
    </ul>
    <Button v-if="calls.hasNextPage.value" size="sm" variant="ghost" :loading="calls.isFetchingNextPage.value" class="self-center" @click="calls.fetchNextPage()">
      {{ t('groups.memory.more') }}
    </Button>
  </section>
</template>
