<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useInfiniteQuery, useQuery } from '@tanstack/vue-query'
import { resourcesApi, type ResourceEntry } from '../../../api/resources'
import Button from '../../../ui/Button.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import Dialog from '../../../ui/Dialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Skeleton from '../../../ui/Skeleton.vue'

const props = defineProps<{ scene: string; entry: ResourceEntry }>()
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()
const text = useInfiniteQuery({
  queryKey: computed(() => ['task-preview', props.scene, props.entry.reference, 'text']),
  queryFn: ({ pageParam }) => resourcesApi.text(props.scene, props.entry.reference, pageParam),
  initialPageParam: 0,
  getNextPageParam: (page) => page.next_offset ?? undefined,
  enabled: computed(() => props.entry.preview === 'text'),
  gcTime: 0,
})
const content = computed(() => text.data.value?.pages.map((page) => page.text).join('') ?? '')
const blob = useQuery({
  queryKey: computed(() => ['task-preview', props.scene, props.entry.reference, 'blob']),
  queryFn: () => resourcesApi.preview(props.scene, props.entry.reference),
  enabled: computed(() => props.entry.preview === 'image' || props.entry.preview === 'pdf'),
  gcTime: 0,
})
const url = ref<string | null>(null)
watch(
  () => blob.data.value,
  (value) => {
    if (url.value) URL.revokeObjectURL(url.value)
    url.value = value ? URL.createObjectURL(value) : null
  },
  { immediate: true },
)
onScopeDispose(() => {
  if (url.value) URL.revokeObjectURL(url.value)
})
const error = computed(() => text.error.value ?? blob.error.value)
const pending = computed(() => (props.entry.preview === 'text' ? text.isPending.value : blob.isPending.value))

const open = computed({
  get: () => true,
  set: (value: boolean) => {
    if (!value) emit('close')
  },
})
</script>

<template>
  <Dialog v-model:open="open" :title="entry.name" size="xl">
    <ErrorNote v-if="error" :title="t('groups.tasks.space.previewFailed')" :error="error" />
    <Skeleton v-else-if="pending" :lines="6" />
    <template v-else-if="entry.preview === 'text'">
      <CodeBlock :code="content" :max-lines="0" class="max-h-[65vh] overflow-auto" />
      <Button
        v-if="text.hasNextPage.value"
        size="sm"
        variant="ghost"
        class="mt-2"
        :loading="text.isFetchingNextPage.value"
        @click="text.fetchNextPage()"
      >
        {{ t('groups.tasks.space.readMore') }}
      </Button>
    </template>
    <img
      v-else-if="entry.preview === 'image' && url"
      :src="url"
      :alt="entry.name"
      class="mx-auto block max-h-[70vh] max-w-full object-contain"
    />
    <iframe v-else-if="entry.preview === 'pdf' && url" :src="url" :title="entry.name" class="h-[70vh] w-full border-0" />
  </Dialog>
</template>
