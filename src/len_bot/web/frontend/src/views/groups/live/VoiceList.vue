<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/vue-query'
import { AudioLines } from '@lucide/vue'
import { audioApi, type AudioItem, type AudioStatus } from '../../../api/audio'
import { keys } from '../../../api/query'
import { developerDetails } from '../../../composables/useDeveloperMode'
import { formatDateTime } from '../../../i18n/format'
import Badge, { type Tone } from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'

const props = defineProps<{ scene: string }>()

const { t } = useI18n()
const client = useQueryClient()
const list = useInfiniteQuery({
  queryKey: computed(() => keys.scene.audio(props.scene)),
  queryFn: ({ pageParam, signal }) => audioApi.list(props.scene, pageParam, signal),
  initialPageParam: 0,
  getNextPageParam: (page) => page.next_offset ?? undefined,
})
const first = computed(() => list.data.value?.pages[0])
const rows = computed(() => list.data.value?.pages.flatMap((page) => page.items) ?? [])
const tones: Record<AudioStatus, Tone> = {
  idle: 'neutral',
  queued: 'neutral',
  running: 'info',
  complete: 'success',
  failed: 'error',
  interrupted: 'warning',
}
const id = (item: AudioItem) => `${item.platform_id}/${item.audio_index}`

const transcribe = useMutation({
  mutationFn: (item: AudioItem) => audioApi.transcribe(props.scene, item),
  onError: (error) =>
    toast.error(t('groups.live.audio.failed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
  onSettled: () => client.invalidateQueries({ queryKey: keys.scene.audio(props.scene) }),
})
async function again(item: AudioItem) {
  const sure = await confirm({
    title: t('groups.live.audio.againTitle'),
    message: t('groups.live.audio.againMessage'),
    confirmLabel: t('groups.live.audio.again'),
    tone: 'primary',
  })
  if (sure) transcribe.mutate(item)
}
const calls = ref<Record<string, unknown>>({})
const reading = useMutation({
  mutationFn: (item: AudioItem) => audioApi.calls(props.scene, item),
  onSuccess: (value, item) => (calls.value = { ...calls.value, [id(item)]: value }),
  onError: (error) =>
    toast.error(t('groups.live.audio.callsFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
})
</script>

<template>
  <div class="flex flex-col gap-4">
    <Skeleton v-if="list.isPending.value" :lines="4" />
    <ErrorNote
      v-else-if="list.isError.value"
      :title="t('groups.live.audio.readFailed')"
      :error="list.error.value"
      :retry="list.refetch"
    />
    <template v-else-if="first">
      <div
        v-if="!first.available"
        class="flex flex-wrap items-center gap-3 rounded-lg border border-line px-4 py-3 text-sm text-muted"
      >
        <span class="min-w-0 flex-1">{{ t('groups.live.audio.unavailable') }}</span>
        <Button size="sm" :to="{ name: 'host-models' }">{{ t('groups.live.audio.toModels') }}</Button>
      </div>
      <ErrorNote
        v-if="first.worker_error"
        :title="t('groups.live.audio.stopped')"
        :error="first.worker_error"
      />
      <EmptyState v-if="!rows.length" :icon="AudioLines" :title="t('groups.live.audio.empty')" compact />
      <ul v-else class="flex list-none flex-col divide-y divide-line border-y border-line">
        <li v-for="item in rows" :key="id(item)" class="flex flex-col gap-2.5 py-3">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex flex-wrap items-center gap-2">
              <Badge :tone="tones[item.status]" dot size="sm">
                {{ t(`groups.live.audio.status.${item.status}`) }}
              </Badge>
              <span class="text-xs text-muted tabular">
                {{
                  [
                    formatDateTime(item.updated, { timeZone: first.timezone }),
                    item.duration !== null
                      ? t('groups.live.audio.seconds', { n: item.duration.toFixed(1) })
                      : '',
                  ]
                    .filter(Boolean)
                    .join(' · ')
                }}
              </span>
            </div>
            <Button
              size="sm"
              variant="ghost"
              :loading="transcribe.isPending.value && transcribe.variables.value === item"
              :disabled="
                !first.available || first.stopping || item.status === 'queued' || item.status === 'running'
              "
              @click="again(item)"
            >
              {{ t('groups.live.audio.again') }}
            </Button>
          </div>
          <audio
            v-if="item.wav_bytes !== null"
            :src="audioApi.wavUrl(scene, item)"
            controls
            preload="none"
            class="h-9 w-full max-w-md"
          />
          <p
            v-if="item.transcript !== null"
            class="text-sm break-words whitespace-pre-wrap"
            :class="item.transcript ? 'text-ink' : 'text-muted'"
          >
            {{ item.transcript || t('groups.live.audio.noText') }}
          </p>
          <ErrorNote v-if="item.error" :title="t('groups.live.audio.itemFailed')" :error="item.error" />
          <template v-if="developerDetails">
            <div v-if="!(id(item) in calls)">
              <Button
                size="sm"
                variant="ghost"
                :loading="reading.isPending.value && reading.variables.value === item"
                @click="reading.mutate(item)"
              >
                {{ t('groups.live.audio.calls') }}
              </Button>
            </div>
            <CodeBlock v-else :code="calls[id(item)]" :max-lines="12" />
          </template>
        </li>
      </ul>
      <div v-if="list.hasNextPage.value">
        <Button
          size="sm"
          variant="ghost"
          :loading="list.isFetchingNextPage.value"
          @click="list.fetchNextPage()"
        >
          {{ t('groups.live.audio.older') }}
        </Button>
      </div>
    </template>
  </div>
</template>
