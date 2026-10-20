<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { learningApi, type LearningSettings } from '../../../api/learning'
import { keys } from '../../../api/query'
import { settingsApi } from '../../../api/settings'
import { readPendingRestart } from '../../../api/hostStore'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import Sheet from '../../../ui/Sheet.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Switch from '../../../ui/Switch.vue'
import { confirm } from '../../../ui/confirm'
import { toast } from '../../../ui/toast'

const props = defineProps<{ scene: string }>()
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const client = useQueryClient()
const config = useQuery({
  queryKey: computed(() => keys.scene.learning(props.scene, 'config')),
  queryFn: ({ signal }) => learningApi.config(props.scene, signal),
})
// Learning needs a model bound to the learner role.
const settings = useQuery({
  queryKey: keys.host.settings(),
  queryFn: ({ signal }) => settingsApi.read(signal),
})
const noLearner = computed(() => {
  const roles = (settings.data.value?.saved.models as { roles?: Record<string, unknown> } | undefined)?.roles
  return Boolean(roles) && !roles!.learner
})

const draft = ref<LearningSettings | null>(null)
const saved = computed(() => config.data.value?.saved ?? null)
const reset = () => (draft.value = saved.value && JSON.parse(JSON.stringify(saved.value)))
watch(saved, reset, { immediate: true })
watch(open, (value) => value && reset())
const dirty = computed(
  () => Boolean(config.data.value) && JSON.stringify(draft.value) !== JSON.stringify(saved.value),
)
watch(dirty, (value) => emit('dirty', value), { immediate: true })

const enabled = computed({
  get: () => draft.value !== null,
  set: (value: boolean) =>
    (draft.value = value
      ? {
          extract: true,
          jargon_extract: false,
          collect_stickers: false,
          reply_effects: false,
          min_messages: 20,
          batch_size: 50,
          idle_seconds: 300,
          max_age_seconds: 1800,
          auto_adopt: false,
          embedding: saved.value?.embedding ?? null,
        }
      : null),
})
const switches = ['extract', 'jargon_extract', 'collect_stickers', 'reply_effects', 'auto_adopt'] as const
const numbers = [
  { key: 'min_messages', min: 1, max: 100 },
  { key: 'batch_size', min: 1, max: 100 },
  { key: 'idle_seconds', min: 1, seconds: true },
  { key: 'max_age_seconds', min: 1, seconds: true },
] as const
const errors = computed<Record<string, string>>(() => {
  const value = draft.value
  const found: Record<string, string> = {}
  if (!value) return found
  for (const { key } of numbers) if (typeof value[key] !== 'number') found[key] = t('common.required')
  if ((value.batch_size ?? 0) < (value.min_messages ?? 0))
    found.batch_size = t('groups.learning.settings.batchTooSmall')
  if ((value.max_age_seconds ?? 0) < (value.idle_seconds ?? 0))
    found.max_age_seconds = t('groups.learning.settings.ageTooSmall')
  return found
})

const save = useMutation({
  mutationFn: () => learningApi.putConfig(props.scene, draft.value),
  onSuccess: (value) => {
    client.setQueryData(keys.scene.learning(props.scene, 'config'), value)
    void client.invalidateQueries({ queryKey: keys.scene.learningAll(props.scene) })
    void client.invalidateQueries({ queryKey: keys.host.settings() })
    void readPendingRestart()
    toast.success(t('common.saved'))
    open.value = false
  },
})
async function close() {
  if (dirty.value && !(await confirm({ title: t('common.unsaved'), confirmLabel: t('common.discard') })))
    return
  reset()
  open.value = false
}
</script>

<template>
  <Sheet
    :open="open"
    :title="t('groups.learning.settings.title')"
    @update:open="(value: boolean) => (value ? (open = true) : close())"
  >
    <Skeleton v-if="config.isPending.value" :lines="6" />
    <ErrorNote
      v-else-if="config.isError.value"
      :title="t('groups.learning.readFailed')"
      :error="config.error.value"
      :retry="config.refetch"
    />
    <div v-else class="flex flex-col gap-5">
      <Field :label="t('groups.learning.settings.enabled')" inline>
        <Switch v-model="enabled" />
      </Field>
      <p
        v-if="draft && (draft.extract || draft.jargon_extract) && noLearner"
        class="flex flex-wrap items-center gap-x-2 rounded-lg bg-warning-bg px-3 py-2.5 text-sm text-warning"
      >
        {{ t('groups.learning.settings.noLearner') }}
        <RouterLink :to="{ name: 'host-models', query: { tab: 'roles' } }" class="font-medium underline">
          {{ t('groups.learning.settings.toModels') }}
        </RouterLink>
      </p>
      <template v-if="draft">
        <Field v-for="key in switches" :key="key" :label="t(`groups.learning.settings.${key}`)" inline>
          <Switch v-model="draft[key]" />
        </Field>
        <div class="grid gap-4 border-t border-line pt-5 sm:grid-cols-2">
          <Field
            v-for="item in numbers"
            :key="item.key"
            :label="t(`groups.learning.settings.${item.key}`)"
            :error="errors[item.key]"
          >
            <NumberInput
              v-model="draft[item.key]"
              :min="item.min"
              :max="'max' in item ? item.max : undefined"
              :unit="'seconds' in item ? t('groups.settings.seconds') : undefined"
            />
          </Field>
        </div>
      </template>
      <ErrorNote
        v-if="save.isError.value"
        :title="t('groups.learning.saveFailed')"
        :error="save.error.value"
      />
    </div>
    <template #footer>
      <Button variant="ghost" :disabled="save.isPending.value" @click="close">
        {{ t('common.cancel') }}
      </Button>
      <Button
        variant="primary"
        :loading="save.isPending.value"
        :disabled="!dirty || Object.keys(errors).length > 0"
        @click="save.mutate()"
      >
        {{ t('common.save') }}
      </Button>
    </template>
  </Sheet>
</template>
