<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ApiError } from '../../api/client'
import { modelsApi } from '../../api/models'
import { keys } from '../../api/query'
import { settingsApi, type SettingsSnapshot } from '../../api/settings'
import { readPendingRestart } from '../../host/store.js'
import { formatDateTime } from '../../i18n/format'
import { groupLabel } from '../../layouts/shell/scenes'
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

const versionOf = (snapshot: SettingsSnapshot) => (snapshot.versions as { limits?: string } | undefined)?.limits
const draft = ref<Limits>(pick(props.snapshot))
/** The version the draft started from; a save against a newer one is refused instead of overwriting it. */
const base = ref(versionOf(props.snapshot))
function adopt(snapshot: SettingsSnapshot) {
  draft.value = pick(snapshot)
  base.value = versionOf(snapshot)
}
const same = (a: Limits, b: Limits) =>
  a.daily_tokens === b.daily_tokens &&
  JSON.stringify(Object.entries(a.scene_daily_tokens).sort()) === JSON.stringify(Object.entries(b.scene_daily_tokens).sort())
const dirty = computed(() => !same(draft.value, saved.value))
watch(
  saved,
  (_, previous) => {
    if (!previous || same(draft.value, previous)) adopt(props.snapshot)
  },
)
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
const save = useMutation({
  mutationFn: () => modelsApi.saveLimits({ ...draft.value, version: base.value }),
  onMutate: () => (conflict.value = null),
  onSuccess: (snapshot) => {
    client.setQueryData(keys.host.settings(), snapshot)
    adopt(snapshot)
    void client.invalidateQueries({ queryKey: keys.host.limits() })
    void readPendingRestart()
    toast.success(t('common.saved'))
  },
  onError: (error) => {
    // Changed in another tab first: load the latest limits so the next save works, and say the edit is gone.
    const detail = error instanceof ApiError && error.status === 409 ? (error.detail as { snapshot?: SettingsSnapshot }) : null
    if (!detail?.snapshot) return
    client.setQueryData(keys.host.settings(), detail.snapshot)
    adopt(detail.snapshot)
    conflict.value = t('models.limits.conflict')
  },
})
const saveError = computed(() =>
  conflict.value ?? (save.isError.value ? describeError(save.error.value, t('ui.error.network')).message : null),
)
</script>

<template>
  <section class="flex min-w-0 flex-col gap-4">
    <h2 class="text-base font-semibold">{{ t('models.limits.title') }}</h2>
    <ErrorNote v-if="state.isError.value" :title="t('models.limits.stateFailed')" :error="state.error.value" :retry="state.refetch" />
    <p v-for="item in blocked" :key="item.scene" class="rounded-md bg-warning-bg px-3 py-2 text-sm text-warning">
      {{
        item.until
          ? t('models.limits.blockedUntil', { name: groupLabel(item.scene), time: formatDateTime(item.until) })
          : t('models.limits.blocked', { name: groupLabel(item.scene) })
      }}
    </p>
    <div class="flex min-w-0 flex-col gap-5 rounded-xl border border-line bg-surface p-5">
      <Field :label="t('models.limits.daily')" class="max-w-xs">
        <NumberInput v-model="draft.daily_tokens" :min="1" :steppers="false" unit="tokens" :placeholder="t('models.limits.unlimited')" />
      </Field>
      <div class="flex flex-col gap-2">
        <h3 class="text-sm font-semibold">{{ t('models.limits.perGroup') }}</h3>
        <ul class="flex list-none flex-col divide-y divide-line">
          <li v-for="scene in scenes" :key="scene" class="py-2">
            <Field :label="groupLabel(scene)" inline>
              <div class="w-44">
                <NumberInput
                  :model-value="sceneLimit(scene)"
                  :min="1"
                  :steppers="false"
                  unit="tokens"
                  size="sm"
                  :placeholder="t('models.limits.followAll')"
                  @update:model-value="(value) => setSceneLimit(scene, value)"
                />
              </div>
            </Field>
          </li>
        </ul>
      </div>
    </div>
    <SaveBar
      :dirty="dirty || Boolean(conflict)"
      :saving="save.isPending.value"
      :error="saveError"
      @save="save.mutate()"
      @discard="
        () => {
          adopt(snapshot)
          conflict = null
        }
      "
    />
  </section>
</template>
