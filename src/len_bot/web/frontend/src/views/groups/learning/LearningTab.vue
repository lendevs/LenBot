<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { GraduationCap, Settings2, TriangleAlert } from '@lucide/vue'
import { learningApi } from '../../../api/learning'
import { keys } from '../../../api/query'
import { useHostEvent } from '../../../realtime/stream'
import Button from '../../../ui/Button.vue'
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

type Kind = 'expressions' | 'jargon' | 'stickers' | 'effects'
const { t } = useI18n()
const client = useQueryClient()
const shownKind = ref<Kind>('expressions')
const settingsOpen = ref(false)

const state = useQuery({
  queryKey: computed(() => keys.scene.learning(props.scene, 'state')),
  queryFn: ({ signal }) => learningApi.state(props.scene, signal),
})
const config = useQuery({
  queryKey: computed(() => keys.scene.learning(props.scene, 'config')),
  queryFn: ({ signal }) => learningApi.config(props.scene, signal),
})
const kinds = computed(() =>
  (['expressions', 'jargon', 'stickers', 'effects'] as const).map((value) => {
    const pending = value === 'expressions' ? state.data.value?.expression_counts.pending : undefined
    const label = t(`groups.learning.kinds.${value}`)
    return { value, label: pending ? `${label} ${pending}` : label }
  }),
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

const failed = (title: string) => (error: unknown) =>
  toast.error(title, { detail: describeError(error, t('ui.error.network')).message })
const learn = useMutation({
  mutationFn: () => learningApi.learnNow(props.scene),
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
async function switchTo(value: Kind) {
  const current = shownKind.value
  if (dirty[current] && !(await confirm({ title: t('common.unsaved'), confirmLabel: t('common.discard') }))) return
  dirty[current] = false
  shownKind.value = value
}
watch(
  () => Object.values(dirty).some(Boolean),
  (value) => emit('dirty', value),
  { immediate: true },
)
</script>

<template>
  <div class="flex flex-col gap-5">
    <div
      v-if="state.data.value?.index?.needs_rebuild"
      class="flex flex-wrap items-center gap-3 rounded-lg bg-warning-bg px-4 py-3 text-sm text-warning"
    >
      <TriangleAlert :size="16" aria-hidden="true" />
      <span class="min-w-0 flex-1">{{ t('groups.learning.needsRebuild') }}</span>
      <Button size="sm" :loading="reindex.isPending.value || Boolean(state.data.value.index.rebuilding)" @click="reindex.mutate()">
        {{ t('groups.learning.reindex') }}
      </Button>
    </div>
    <div
      v-if="config.data.value && config.data.value.saved === null"
      class="flex flex-wrap items-center gap-3 rounded-lg border border-line px-4 py-3 text-sm"
    >
      <span class="min-w-0 flex-1 text-muted">{{ t('groups.learning.off') }}</span>
      <Button size="sm" variant="primary" @click="settingsOpen = true">{{ t('groups.learning.turnOn') }}</Button>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <SegmentedControl v-model="kind" :options="kinds" :label="t('groups.tabs.learning')" />
      <div class="ml-auto flex items-center gap-2">
        <Button
          v-if="state.data.value?.enabled"
          size="sm"
          :icon="GraduationCap"
          :loading="learn.isPending.value"
          @click="learn.mutate()"
        >
          {{ t('groups.learning.learnNow') }}
        </Button>
        <Button size="sm" variant="ghost" :icon="Settings2" @click="settingsOpen = true">
          {{ t('groups.learning.settings.title') }}
        </Button>
      </div>
    </div>

    <ExpressionList v-if="kind === 'expressions'" :scene="scene" @dirty="(value: boolean) => (dirty.expressions = value)" />
    <JargonList v-else-if="kind === 'jargon'" :scene="scene" @dirty="(value: boolean) => (dirty.jargon = value)" />
    <StickerList v-else-if="kind === 'stickers'" :scene="scene" @dirty="(value: boolean) => (dirty.stickers = value)" />
    <ReplyEffects v-else :scene="scene" :time-zone="timeZone" />

    <LearningSettings
      v-model:open="settingsOpen"
      :scene="scene"
      @dirty="(value: boolean) => (dirty.settings = value)"
    />
  </div>
</template>
