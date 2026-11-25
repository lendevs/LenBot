<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { GraduationCap, Settings2, TriangleAlert } from '@lucide/vue'
import { learningApi, type JargonView, type Review, type StickerFilter } from '../../../api/learning'
import { keys } from '../../../api/query'
import { useHostEvent } from '../../../realtime/stream'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import ExpressionList from './ExpressionList.vue'
import JargonList from './JargonList.vue'
import LearningSettings from './LearningSettings.vue'
import ReplyEffects from './ReplyEffects.vue'
import StickerList from './StickerList.vue'

const props = defineProps<{ scene: string; timeZone: string }>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

const VALID_KINDS = ['expressions', 'jargon', 'stickers', 'effects'] as const
type Kind = (typeof VALID_KINDS)[number]
const isKind = (value: unknown): value is Kind =>
  typeof value === 'string' && (VALID_KINDS as readonly string[]).includes(value)

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const client = useQueryClient()
const shownKind = ref<Kind>(isKind(route.query.kind) ? route.query.kind : 'expressions')
const settingsOpen = ref(false)
const expressionFilter = ref<Review>('pending')
const jargonFilter = ref<JargonView>('learned')
const stickerFilter = ref<StickerFilter>('pending')

const reviewFilters = computed(() =>
  (['pending', 'adopted', 'rejected'] as const).map((value) => ({
    value,
    label: t(`groups.learning.review.${value}`),
  })),
)
const jargonFilters = computed(() =>
  (['learned', 'adopted', 'uncertain', 'ordinary', 'rejected'] as const).map((value) => ({
    value,
    label: t(`groups.learning.jargon.${value === 'ordinary' ? 'excluded' : value}`),
  })),
)

const state = useQuery({
  queryKey: computed(() => keys.scene.learning(props.scene, 'state')),
  queryFn: ({ signal }) => learningApi.state(props.scene, signal),
})
const config = useQuery({
  queryKey: computed(() => keys.scene.learning(props.scene, 'config')),
  queryFn: ({ signal }) => learningApi.config(props.scene, signal),
})
const jargonState = useQuery({
  queryKey: computed(() => keys.scene.learning(props.scene, 'jargon-state')),
  queryFn: ({ signal }) => learningApi.jargonState(props.scene, signal),
})
const stickerState = useQuery({
  queryKey: computed(() => keys.scene.learning(props.scene, 'sticker-state')),
  queryFn: ({ signal }) => learningApi.stickerState(props.scene, signal),
})
// Shares the first-page query key with StickerList so pending count causes no duplicate request.
const pendingStickers = useQuery({
  queryKey: computed(() => keys.scene.learning(props.scene, 'stickers', 'pending', 0)),
  queryFn: ({ signal }) => learningApi.stickers(props.scene, 'pending', 0, signal),
})
const effectsState = useQuery({
  queryKey: computed(() => keys.scene.learning(props.scene, 'effects', 7)),
  queryFn: ({ signal }) => learningApi.effects(props.scene, 7, signal),
})

const stickerFilters = computed(() => {
  const counts = stickerState.data.value?.counts
  return (['pending', 'adopted', 'rejected', 'queued', 'failed'] as const).map((value) => {
    if (value === 'queued' || value === 'failed') {
      const label = t(`groups.learning.sticker.${value}`)
      const count = counts?.[value] ?? 0
      return { value, label: count ? `${label} ${count}` : label }
    }
    return { value, label: t(`groups.learning.review.${value}`) }
  })
})

const kinds = computed(() =>
  (['expressions', 'jargon', 'stickers', 'effects'] as const).map((value) => {
    const pending =
      value === 'expressions'
        ? state.data.value?.expression_counts.pending
        : value === 'stickers'
          ? pendingStickers.data.value?.total
          : undefined
    const label = t(`groups.learning.kinds.${value}`)
    return { value, label: pending ? `${label} ${pending}` : label }
  }),
)

const latest = computed(() => state.data.value?.latest ?? null)
const latestRunning = computed(() => latest.value?.status === 'running')
const latestError = computed(() =>
  latest.value && (latest.value.status === 'failed' || latest.value.error)
    ? latest.value.error || latest.value.status
    : null,
)

// Learning runs in the background and only announces itself as a general change.
let timer: ReturnType<typeof setTimeout> | undefined
useHostEvent('host.changed', () => {
  if (timer) return
  timer = setTimeout(() => {
    timer = undefined
    void client.invalidateQueries({ queryKey: keys.scene.learningAll(props.scene) })
  }, 2000)
})
onBeforeUnmount(() => clearTimeout(timer))

const failed = (title: string) => (error: unknown) =>
  toast.error(title, { detail: describeError(error, t('ui.error.network')).message })

const activeTrigger = computed(() => {
  if (shownKind.value === 'jargon') {
    return {
      enabled: Boolean(jargonState.data.value?.enabled),
      label: t('groups.learning.jargon.runNow'),
      started: t('groups.learning.jargon.started'),
      run: () => learningApi.runJargon(props.scene),
    }
  }
  if (shownKind.value === 'stickers') {
    return {
      enabled: Boolean(stickerState.data.value?.enabled),
      label: t('groups.learning.sticker.runNow'),
      started: t('groups.learning.sticker.started'),
      run: () => learningApi.runStickers(props.scene),
    }
  }
  if (shownKind.value === 'effects') {
    return {
      enabled: Boolean(effectsState.data.value?.enabled),
      label: t('groups.learning.effects.runNow'),
      started: t('groups.learning.effects.started'),
      run: () => learningApi.runEffects(props.scene),
    }
  }
  return {
    enabled: Boolean(state.data.value?.enabled),
    label: t('groups.learning.learnNow'),
    started: t('groups.learning.started'),
    run: () => learningApi.learnNow(props.scene),
  }
})

const triggerRun = useMutation({
  mutationFn: () => activeTrigger.value.run(),
  onSuccess: () => toast.success(activeTrigger.value.started),
  onError: failed(t('groups.learning.startFailed')),
  onSettled: () => client.invalidateQueries({ queryKey: keys.scene.learningAll(props.scene) }),
})
const retryLatest = useMutation({
  mutationFn: () => learningApi.retryLearning(props.scene),
  onSuccess: () => toast.success(t('groups.learning.started')),
  onError: failed(t('groups.learning.startFailed')),
  onSettled: () => client.invalidateQueries({ queryKey: keys.scene.learning(props.scene, 'state') }),
})
const reindex = useMutation({
  mutationFn: () => learningApi.reindex(props.scene),
  onSuccess: (value) => toast.success(t('groups.learning.reindexed', { n: value.expressions })),
  onError: failed(t('groups.learning.reindexFailed')),
  onSettled: () => client.invalidateQueries({ queryKey: keys.scene.learningAll(props.scene) }),
})

const dirty = reactive<Record<string, boolean>>({})
/** Leaving a list with an unsaved edit asks first; the edit is dropped with the list. */
const kind = computed({
  get: () => shownKind.value,
  set: (value: Kind) => void switchTo(value),
})
async function switchTo(value: Kind, updateRoute = true) {
  const current = shownKind.value
  if (value === current) return
  if (dirty[current] && !(await confirm({ title: t('common.unsaved'), confirmLabel: t('common.discard') }))) {
    if (!updateRoute) {
      const next = { ...route.query }
      if (current === 'expressions') delete next.kind
      else next.kind = current
      void router.replace({ query: next })
    }
    return
  }
  dirty[current] = false
  shownKind.value = value
  if (updateRoute) {
    const next = { ...route.query }
    if (value === 'expressions') delete next.kind
    else next.kind = value
    void router.replace({ query: next })
  }
}
watch(
  () => route.query.kind,
  (value) => {
    const target: Kind = isKind(value) ? value : 'expressions'
    if (target !== shownKind.value) void switchTo(target, false)
  },
)
watch(
  () => Object.values(dirty).some(Boolean),
  (value) => emit('dirty', value),
  { immediate: true },
)
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <div
      v-if="state.data.value?.index?.needs_rebuild"
      class="flex flex-wrap items-center gap-3 rounded-lg bg-warning-bg px-4 py-3 text-sm text-warning"
    >
      <TriangleAlert :size="16" class="shrink-0" aria-hidden="true" />
      <span class="min-w-0 flex-1">{{ t('groups.learning.needsRebuild') }}</span>
      <Button
        size="sm"
        :loading="reindex.isPending.value || Boolean(state.data.value.index.rebuilding)"
        @click="reindex.mutate()"
      >
        {{ t('groups.learning.reindex') }}
      </Button>
    </div>
    <div
      v-if="config.data.value && config.data.value.saved === null"
      class="flex flex-wrap items-center gap-3 rounded-lg bg-fill px-4 py-3 text-sm"
    >
      <span class="min-w-0 flex-1 text-muted">{{ t('groups.learning.off') }}</span>
      <Button size="sm" variant="primary" @click="settingsOpen = true">
        {{ t('groups.learning.turnOn') }}
      </Button>
    </div>
    <ErrorNote
      v-if="latestError"
      :title="t('groups.learning.latestFailed')"
      :error="latestError"
      :retry="state.data.value?.enabled ? () => retryLatest.mutateAsync() : undefined"
    />

    <div class="flex flex-wrap items-center gap-2.5">
      <SegmentedControl v-model="kind" :options="kinds" :label="t('groups.tabs.learning')" />
      <template v-if="kind !== 'effects'">
        <span class="h-4 w-px bg-line max-sm:hidden" aria-hidden="true" />
        <SegmentedControl
          v-if="kind === 'expressions'"
          v-model="expressionFilter"
          :options="reviewFilters"
          size="sm"
          :label="t('groups.learning.kinds.expressions')"
        />
        <SegmentedControl
          v-else-if="kind === 'jargon'"
          :model-value="jargonFilter"
          :options="jargonFilters"
          size="sm"
          :label="t('groups.learning.kinds.jargon')"
          @update:model-value="(value: JargonView) => (jargonFilter = value)"
        />
        <SegmentedControl
          v-else
          v-model="stickerFilter"
          :options="stickerFilters"
          size="sm"
          :label="t('groups.learning.kinds.stickers')"
        />
      </template>
      <div class="ml-auto flex flex-wrap items-center gap-2">
        <Badge v-if="latestRunning" tone="info" dot pulse>
          {{ t('groups.learning.running') }}
        </Badge>
        <Button
          v-if="activeTrigger.enabled"
          size="sm"
          :icon="GraduationCap"
          :loading="triggerRun.isPending.value"
          @click="triggerRun.mutate()"
        >
          {{ activeTrigger.label }}
        </Button>
        <Button size="sm" variant="ghost" :icon="Settings2" @click="settingsOpen = true">
          {{ t('groups.learning.settings.title') }}
        </Button>
      </div>
    </div>

    <ExpressionList
      v-if="kind === 'expressions'"
      v-model:filter="expressionFilter"
      :scene="scene"
      @dirty="(value: boolean) => (dirty.expressions = value)"
    />
    <JargonList
      v-else-if="kind === 'jargon'"
      v-model:filter="jargonFilter"
      :scene="scene"
      @dirty="(value: boolean) => (dirty.jargon = value)"
    />
    <StickerList
      v-else-if="kind === 'stickers'"
      v-model:filter="stickerFilter"
      :scene="scene"
      @dirty="(value: boolean) => (dirty.stickers = value)"
    />
    <ReplyEffects v-else :scene="scene" :time-zone="timeZone" />

    <LearningSettings
      v-model:open="settingsOpen"
      :scene="scene"
      @dirty="(value: boolean) => (dirty.settings = value)"
    />
  </div>
</template>
