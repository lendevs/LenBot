<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useInfiniteQuery, useQuery } from '@tanstack/vue-query'
import { Download } from '@lucide/vue'
import { resourcesApi, type ResourceEntry } from '../../../api/resources'
import Button from '../../../ui/Button.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import Dialog from '../../../ui/Dialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import MarkdownText from '../../../ui/MarkdownText.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Skeleton from '../../../ui/Skeleton.vue'

const props = defineProps<{
  scene: string
  entry: Pick<ResourceEntry, 'name' | 'preview' | 'reference'>
}>()
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

const isMarkdown = computed(
  () => props.entry.preview === 'text' && /\.(?:md|markdown)$/i.test(props.entry.name),
)
const mdView = ref<'rendered' | 'source'>('rendered')
const mdOptions = computed(() => [
  { value: 'rendered' as const, label: t('groups.tasks.space.previewRendered') },
  { value: 'source' as const, label: t('groups.tasks.space.previewSource') },
])
const backdrop = ref<'light' | 'dark'>('light')
const backdropOptions = computed(() => [
  { value: 'light' as const, label: t('groups.tasks.space.backdropLight') },
  { value: 'dark' as const, label: t('groups.tasks.space.backdropDark') },
])
watch(
  () => props.entry,
  () => {
    mdView.value = 'rendered'
  },
)

const open = computed({
  get: () => true,
  set: (value: boolean) => {
    if (!value) emit('close')
  },
})
</script>

<template>
  <Dialog v-model:open="open" :title="entry.name" size="xl">
    <template #header>
      <div class="ml-auto flex shrink-0 items-center gap-2">
        <SegmentedControl
          v-if="isMarkdown && !pending && !error"
          v-model="mdView"
          :options="mdOptions"
          size="sm"
          :label="entry.name"
        />
        <SegmentedControl
          v-else-if="entry.preview === 'image' && url && !error"
          v-model="backdrop"
          :options="backdropOptions"
          size="sm"
          :label="entry.name"
        />
        <Button
          size="sm"
          variant="ghost"
          :icon="Download"
          :href="resourcesApi.downloadUrl(scene, entry.reference)"
          :download="entry.name"
        >
          {{ t('common.download') }}
        </Button>
      </div>
    </template>
    <ErrorNote v-if="error" :title="t('groups.tasks.space.previewFailed')" :error="error" />
    <Skeleton v-else-if="pending" :lines="6" />
    <template v-else-if="entry.preview === 'text'">
      <MarkdownText v-if="isMarkdown && mdView === 'rendered'" :text="content" size="sm" />
      <CodeBlock v-else :code="content" :max-lines="0" />
      <div v-if="text.hasNextPage.value" class="mt-2">
        <Button
          size="sm"
          variant="ghost"
          :loading="text.isFetchingNextPage.value"
          @click="text.fetchNextPage()"
        >
          {{ t('groups.tasks.space.readMore') }}
        </Button>
      </div>
    </template>
    <div
      v-else-if="entry.preview === 'image' && url"
      class="grid place-items-center overflow-hidden rounded-lg border border-line p-4 transition-colors"
      :class="backdrop === 'dark' ? 'bg-black text-white' : 'bg-white text-black'"
    >
      <img :src="url" :alt="entry.name" class="mx-auto block max-h-[68vh] max-w-full object-contain" />
    </div>
    <iframe
      v-else-if="entry.preview === 'pdf' && url"
      :src="url"
      :title="entry.name"
      class="h-[70vh] w-full border-0"
    />
  </Dialog>
</template>
