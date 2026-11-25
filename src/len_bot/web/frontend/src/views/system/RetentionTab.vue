<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery } from '@tanstack/vue-query'
import { Eraser } from '@lucide/vue'
import { host } from '../../api/hostStore'
import { keys } from '../../api/query'
import { systemApi, systemOf, type Retention, type RetentionCounts } from '../../api/system'
import { developerDetails } from '../../composables/useDeveloperMode'
import { groupLabel, sceneSecondaryId } from '../../layouts/shell/scenes'
import Button from '../../ui/Button.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import FormSection from '../../ui/FormSection.vue'
import NumberInput from '../../ui/NumberInput.vue'
import SaveBar from '../../ui/SaveBar.vue'
import Skeleton from '../../ui/Skeleton.vue'
import Switch from '../../ui/Switch.vue'
import { confirm } from '../../ui/confirm'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'
import RawRecord from '../groups/tasks/RawRecord.vue'
import { copy, useSettingsDraft } from './draft'

const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const uid = useId()
const stashed = ref<Retention | null>(null)
const status = useQuery({
  queryKey: keys.system.retention(),
  queryFn: ({ signal }) => systemApi.retention(signal),
})
const form = useSettingsDraft<Retention | null>({
  pick: (snapshot) => systemOf(snapshot).retention,
  section: 'retention',
  reset: () => (stashed.value = null),
  save: (value) => systemApi.saveRetention(value),
  onSaved: () => void status.refetch(),
})
const { settings, draft } = form
watch(form.dirty, (dirty) => emit('dirty', dirty), { immediate: true })

const scenes = computed(() => (settings.data.value ? Object.keys(settings.data.value.saved.scenes) : []))

function toggle(on: boolean) {
  if (!on) {
    if (draft.value) stashed.value = copy(draft.value)
    draft.value = null
    return
  }
  draft.value = stashed.value
    ? copy(stashed.value)
    : form.saved.value
      ? copy(form.saved.value)
      : { request_days: 7, timeline_days: 90, message_days: {} }
}
function setDays(scene: string, days: number | null) {
  if (!draft.value) return
  const next = { ...draft.value.message_days }
  if (days === null) delete next[scene]
  else next[scene] = days
  draft.value.message_days = next
}

const errors = computed(() => {
  const result: Record<string, string> = {}
  const value = draft.value
  if (!value) return result
  if (value.request_days === null) result.request = t('system.required')
  if (value.timeline_days === null) result.timeline = t('system.required')
  return result
})
const invalid = computed(() => Object.keys(errors.value).length > 0)

const restartRequired = computed(() =>
  Boolean(settings.data.value?.restart_required?.retention || host.restart?.sections?.includes('retention')),
)
const pruneBlockedReason = computed(() =>
  form.dirty.value
    ? t('system.retention.pruneBlockedDirty')
    : restartRequired.value
      ? t('system.retention.pruneBlockedRestart')
      : null,
)

const kinds = [
  'messages',
  'turns',
  'model_snapshots',
  'auxiliary_snapshots',
  'task_snapshots',
  'memory_snapshots',
  'extraction_jobs',
  'notices',
] as const
const summary = (counts: RetentionCounts | null | undefined) =>
  kinds
    .filter((kind) => counts?.[kind])
    .map((kind) => t(`system.retention.counts.${kind}`, { n: counts![kind] }, counts![kind]!))
    .join(t('system.retention.separator'))
const preview = computed(() => summary(status.data.value?.preview))

const prune = useMutation({
  mutationFn: () => systemApi.prune(),
  onSuccess: (result) => {
    const text = summary(result)
    toast.success(text ? t('system.retention.pruned', { items: text }) : t('system.retention.nothing'))
    void status.refetch()
  },
  onError: (error) => {
    toast.error(t('system.retention.pruneFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    })
    void status.refetch()
  },
})
async function confirmPrune() {
  if (pruneBlockedReason.value) return
  const sure = await confirm({
    title: t('system.retention.pruneTitle'),
    message: t('system.retention.pruneMessage', { items: preview.value }),
    confirmLabel: t('system.retention.prune'),
    tone: 'danger',
  })
  if (sure) prune.mutate()
}
</script>

<template>
  <Skeleton v-if="settings.isPending.value" :lines="6" />
  <ErrorNote
    v-else-if="settings.isError.value"
    :title="t('system.readFailed')"
    :error="settings.error.value"
    :retry="settings.refetch"
  />
  <div v-else-if="draft !== undefined" class="flex min-w-0 max-w-3xl flex-col gap-6">
    <div class="flex min-w-0 flex-col gap-6">
      <Field :label="t('system.retention.on')" inline>
        <Switch :model-value="draft !== null" @update:model-value="toggle" />
      </Field>
      <template v-if="draft">
        <FormSection>
          <Field :label="t('system.retention.request')" :error="errors.request">
            <NumberInput v-model="draft.request_days" :min="1" :unit="t('system.retention.days')" />
          </Field>
          <Field :label="t('system.retention.timeline')" :error="errors.timeline">
            <NumberInput v-model="draft.timeline_days" :min="32" :unit="t('system.retention.days')" />
          </Field>
        </FormSection>
        <FormSection :title="t('system.retention.messages')" :columns="1">
          <ul v-if="scenes.length" class="flex list-none flex-col divide-y divide-line border-y border-line">
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
                  :model-value="draft.message_days[scene] ?? null"
                  :min="1"
                  size="sm"
                  :placeholder="t('system.retention.forever')"
                  :unit="t('system.retention.days')"
                  @update:model-value="(days: number | null) => setDays(scene, days)"
                />
              </div>
            </li>
          </ul>
          <p v-else class="text-sm text-muted">{{ t('system.retention.noGroups') }}</p>
        </FormSection>
      </template>
    </div>

    <section v-if="status.isPending.value" class="flex min-w-0 flex-col gap-3 border-t border-line pt-6">
      <Skeleton :lines="3" />
    </section>
    <section
      v-else-if="status.data.value?.enabled"
      class="flex min-w-0 flex-col gap-3 border-t border-line pt-6"
    >
      <header class="flex flex-wrap items-center justify-between gap-2">
        <h3 class="text-base font-semibold text-ink">{{ t('system.retention.now') }}</h3>
        <Button
          size="sm"
          variant="danger"
          :icon="Eraser"
          :loading="prune.isPending.value"
          :disabled="status.data.value.busy || !preview || Boolean(pruneBlockedReason)"
          @click="confirmPrune"
        >
          {{ t('system.retention.prune') }}
        </Button>
      </header>
      <p
        v-if="pruneBlockedReason"
        role="status"
        class="rounded-lg bg-warning-bg px-3.5 py-2.5 text-sm text-warning"
      >
        {{ pruneBlockedReason }}
      </p>
      <ErrorNote
        v-if="status.data.value.error"
        :title="t('system.retention.stopped')"
        :error="status.data.value.error"
      />
      <p class="text-sm text-ink-2 tabular">
        {{ preview ? t('system.retention.next', { items: preview }) : t('system.retention.clean') }}
      </p>
      <RawRecord v-if="developerDetails" :label="t('system.retention.raw')" :code="status.data.value" />
    </section>
    <ErrorNote
      v-else-if="status.isError.value"
      :title="t('system.retention.readFailed')"
      :error="status.error.value"
      :retry="status.refetch"
    />
    <SaveBar
      :dirty="form.dirty.value"
      :saving="form.saving.value"
      :error="form.saveError.value"
      :raw-error="form.saveRawError.value"
      :invalid="invalid"
      @save="form.submit"
      @discard="form.discard"
    />
  </div>
</template>
