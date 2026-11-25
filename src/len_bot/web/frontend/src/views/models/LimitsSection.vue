<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ApiError } from '../../api/client'
import { modelsApi } from '../../api/models'
import { keys } from '../../api/query'
import { settingsApi, type SettingsSnapshot } from '../../api/settings'
import { readPendingRestart } from '../../api/hostStore'
import { formatDateTime } from '../../i18n/format'
import { groupLabel, sceneSecondaryId } from '../../layouts/shell/scenes'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import NumberInput from '../../ui/NumberInput.vue'
import SaveBar from '../../ui/SaveBar.vue'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'

interface Limits {
  daily_tokens: number | null
  scene_daily_tokens: Record<string, number>
}

const props = defineProps<{ snapshot: SettingsSnapshot }>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const uid = useId()
const client = useQueryClient()
const pick = (snapshot: SettingsSnapshot): Limits => {
  const value = snapshot.saved.limits as unknown as Limits
  return { daily_tokens: value.daily_tokens, scene_daily_tokens: { ...value.scene_daily_tokens } }
}
const saved = computed(() => pick(props.snapshot))
const scenes = computed(() => Object.keys(props.snapshot.saved.scenes))

const state = useQuery({ queryKey: keys.host.limits(), queryFn: ({ signal }) => settingsApi.limits(signal) })
// Speech limits are shown on each group's settings; only the token limit stops a group here.
const blocked = computed(() =>
  (state.data.value?.scenes ?? []).filter((item) => item.blocked && item.speech.blocked_until === null),
)

const cloneLimits = (value: Limits): Limits => ({
  daily_tokens: value.daily_tokens,
  scene_daily_tokens: { ...value.scene_daily_tokens },
})
const versionOf = (snapshot: SettingsSnapshot) =>
  (snapshot.versions as { limits?: string } | undefined)?.limits
const draft = ref<Limits>(pick(props.snapshot))
const adopted = ref<Limits>(cloneLimits(draft.value))
/** The version the draft started from; a save against a newer one is refused instead of overwriting it. */
const base = ref(versionOf(props.snapshot))
function adopt(snapshot: SettingsSnapshot) {
  const next = pick(snapshot)
  draft.value = next
  adopted.value = cloneLimits(next)
  base.value = versionOf(snapshot)
}
const same = (a: Limits, b: Limits) =>
  a.daily_tokens === b.daily_tokens &&
  JSON.stringify(Object.entries(a.scene_daily_tokens).sort()) ===
    JSON.stringify(Object.entries(b.scene_daily_tokens).sort())
const dirty = computed(() => !same(draft.value, saved.value))
watch(saved, (_, previous) => {
  if (!previous || same(draft.value, previous)) adopt(props.snapshot)
})
watch(dirty, (value) => emit('dirty', value), { immediate: true })

/** A group's own limit; empty follows the overall one. */
const sceneLimit = (scene: string) => draft.value.scene_daily_tokens[scene] ?? null
function setSceneLimit(scene: string, value: number | null) {
  const next = { ...draft.value.scene_daily_tokens }
  if (value === null) delete next[scene]
  else next[scene] = value
  draft.value.scene_daily_tokens = next
}

const conflict = ref<string | null>(null)
const rejectedDraft = ref<Limits | null>(null)
const save = useMutation({
  mutationFn: () => modelsApi.saveLimits({ ...draft.value, version: base.value }),
  onMutate: () => {
    conflict.value = null
    rejectedDraft.value = null
  },
  onSuccess: (snapshot) => {
    client.setQueryData(keys.host.settings(), snapshot)
    adopt(snapshot)
    rejectedDraft.value = null
    void client.invalidateQueries({ queryKey: keys.host.limits() })
    void readPendingRestart()
    toast.success(t('common.saved'))
  },
  onError: (error) => {
    // Changed in another tab first: stash the user's draft and load the latest version so reapplying works cleanly.
    const data =
      error instanceof ApiError && error.code === 'limits_conflict'
        ? (error.data as { snapshot?: SettingsSnapshot })
        : null
    if (!data?.snapshot) return
    const attempted = cloneLimits(draft.value)
    const latest = pick(data.snapshot)
    rejectedDraft.value = same(attempted, latest) ? null : attempted
    client.setQueryData(keys.host.settings(), data.snapshot)
    adopt(data.snapshot)
    conflict.value = t('models.limits.conflict')
  },
})
function reapplyRejected() {
  if (!rejectedDraft.value) return
  const validScenes = new Set(scenes.value)
  draft.value = {
    daily_tokens: rejectedDraft.value.daily_tokens,
    scene_daily_tokens: Object.fromEntries(
      Object.entries(rejectedDraft.value.scene_daily_tokens).filter(([scene]) => validScenes.has(scene)),
    ),
  }
  rejectedDraft.value = null
  conflict.value = null
  if (save.isError.value) save.reset()
}
const saveError = computed(
  () =>
    conflict.value ??
    (save.isError.value ? describeError(save.error.value, t('ui.error.network')).message : null),
)
const saveRawError = computed(() =>
  !conflict.value && save.isError.value ? describeError(save.error.value, t('ui.error.network')).raw : null,
)
watch(
  draft,
  () => {
    if (!same(draft.value, adopted.value)) {
      conflict.value = null
      rejectedDraft.value = null
      if (save.isError.value) save.reset()
    }
  },
  { deep: true },
)
</script>

<template>
  <section class="flex min-w-0 flex-col gap-5 border-t border-line pt-6">
    <h2 class="text-base font-semibold text-ink">{{ t('models.limits.title') }}</h2>
    <ErrorNote
      v-if="state.isError.value"
      :title="t('models.limits.stateFailed')"
      :error="state.error.value"
      :retry="state.refetch"
    />
    <p
      v-for="item in blocked"
      :key="item.scene"
      class="rounded-lg bg-warning-bg px-3.5 py-2.5 text-sm text-warning tabular"
    >
      {{
        item.until
          ? t('models.limits.blockedUntil', {
              name: groupLabel(item.scene),
              time: formatDateTime(item.until),
            })
          : t('models.limits.blocked', { name: groupLabel(item.scene) })
      }}
    </p>
    <div class="flex min-w-0 max-w-3xl flex-col gap-6">
      <div class="max-w-xs">
        <Field :label="t('models.limits.daily')">
          <NumberInput
            v-model="draft.daily_tokens"
            :min="1"
            :steppers="false"
            unit="tokens"
            :placeholder="t('models.limits.unlimited')"
          />
        </Field>
      </div>
      <div v-if="scenes.length" class="flex flex-col gap-2.5">
        <h3 class="text-sm font-semibold text-ink">{{ t('models.limits.perGroup') }}</h3>
        <ul class="flex list-none flex-col divide-y divide-line border-y border-line">
          <li
            v-for="(scene, index) in scenes"
            :key="scene"
            class="flex items-center justify-between gap-4 py-2.5"
          >
            <label :for="`${uid}-${index}`" class="min-w-0 flex-1 cursor-pointer">
              <span class="block truncate text-sm font-medium text-ink">{{ groupLabel(scene) }}</span>
              <span
                v-if="sceneSecondaryId(scene)"
                class="block truncate font-mono text-xs text-muted tabular"
              >
                {{ sceneSecondaryId(scene) }}
              </span>
            </label>
            <div class="w-36 shrink-0 sm:w-44">
              <NumberInput
                :id="`${uid}-${index}`"
                :model-value="sceneLimit(scene)"
                :min="1"
                :steppers="false"
                unit="tokens"
                size="sm"
                :placeholder="t('models.limits.followAll')"
                @update:model-value="(value) => setSceneLimit(scene, value)"
              />
            </div>
          </li>
        </ul>
      </div>
    </div>
    <SaveBar
      :dirty="dirty || Boolean(conflict)"
      :saving="save.isPending.value"
      :error="saveError"
      :raw-error="saveRawError"
      :invalid="!dirty"
      :action-label="rejectedDraft ? t('models.limits.reapply') : undefined"
      @save="dirty && save.mutate()"
      @action="reapplyRejected"
      @discard="
        () => {
          adopt(snapshot)
          conflict = null
          rejectedDraft = null
          save.reset()
        }
      "
    />
  </section>
</template>
