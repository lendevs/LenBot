<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { ArrowUpRight, MessageCircle, RotateCcw, Square } from '@lucide/vue'
import { personasApi, type PersonaRole, type Trial } from '../../../api/personas'
import { trialSource, trialsApi } from '../../../api/trials'
import ChatPanel from '../../playground/chat/ChatPanel.vue'
import { groupLabel } from '../../../layouts/shell/scenes'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import Select from '../../../ui/Select.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import { useProfile } from './profileForm'

defineProps<{ role: PersonaRole; scene: string }>()

const { t } = useI18n()
const form = useProfile()
const context = ref('0')
const contextOptions = computed(() =>
  ['0', '20', '50', '100'].map((value) => ({
    value,
    label: value === '0' ? t('personas.detail.trial.blank') : t('personas.detail.trial.recent', { n: value }),
  })),
)
const problem = computed(() => form.problem('identity') ?? form.problem('speech'))
const current = () => JSON.stringify(form.draft.value)

const trial = ref<Trial | null>(null)
/** The draft the running trial started from; later edits show as a change until it restarts. */
const started = ref('')
const changed = computed(() => trial.value !== null && current() !== started.value)

// The host keeps one trial running; after a reload this role's draft trial is picked up again.
onMounted(async () => {
  const directory = form.saved.data.value?.directory
  const running = (await trialsApi.list()).items.find(
    (item) => item.active && item.draft_source === directory,
  )
  if (running && !trial.value) {
    started.value = current()
    trial.value = running
  }
})

async function launch(scene: string) {
  const snapshot = current()
  const value = await personasApi.trial(scene, Number(context.value), await form.draftFiles())
  started.value = snapshot
  return value
}
const start = useMutation({
  mutationFn: launch,
  onSuccess: (value) => (trial.value = value),
})
const restart = useMutation({
  mutationFn: async ({ id, scene }: { id: string; scene: string }) => {
    await personasApi.stopTrial(id)
    trial.value = null
    return launch(scene)
  },
  onSuccess: (value) => (trial.value = value),
  onError: (error) =>
    toast.error(t('personas.detail.trial.restartFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
})
const stop = useMutation({
  mutationFn: (id: string) => personasApi.stopTrial(id),
  onSuccess: () => (trial.value = null),
  onError: (error) =>
    toast.error(t('personas.detail.trial.stopFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
})
async function end() {
  const sure = await confirm({
    title: t('personas.detail.trial.stopTitle'),
    message: t('personas.detail.trial.stopMessage'),
    confirmLabel: t('personas.detail.trial.stop'),
  })
  if (sure && trial.value) stop.mutate(trial.value.id)
}
</script>

<template>
  <div v-if="trial" class="flex min-w-0 flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <h3 class="min-w-0 flex-1 truncate text-base font-semibold">
        {{ t('personas.detail.trial.running', { name: trial.persona, group: groupLabel(trial.scene) }) }}
      </h3>
      <Badge v-if="changed" tone="warning">{{ t('personas.detail.trial.changed') }}</Badge>
      <Button
        v-if="changed"
        size="sm"
        :icon="RotateCcw"
        :loading="restart.isPending.value"
        :disabled="!scene || Boolean(problem)"
        @click="restart.mutate({ id: trial.id, scene })"
      >
        {{ t('personas.detail.trial.restart') }}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        :icon-right="ArrowUpRight"
        :to="{ name: 'host-trials', query: { trial: trial.id } }"
      >
        {{ t('personas.detail.trial.openPlayground') }}
      </Button>
      <Button size="sm" :icon="Square" :loading="stop.isPending.value" @click="end">
        {{ t('personas.detail.trial.stop') }}
      </Button>
    </div>
    <ChatPanel :key="trial.id" :source="trialSource(trial.id)" />
  </div>
  <form v-else class="flex max-w-3xl flex-col gap-6" @submit.prevent="start.mutate(scene)">
    <FormSection :title="t('personas.detail.trial.title')">
      <Field :label="t('personas.detail.trial.context')">
        <Select v-model="context" :options="contextOptions" />
      </Field>
    </FormSection>
    <ErrorNote
      v-if="start.isError.value"
      :title="t('personas.detail.trial.startFailed')"
      :error="start.error.value"
    />
    <div>
      <Button
        type="submit"
        variant="primary"
        :icon="MessageCircle"
        :loading="start.isPending.value"
        :disabled="!scene || Boolean(problem) || !form.draft.value"
      >
        {{ t('personas.detail.trial.start') }}
      </Button>
    </div>
  </form>
</template>
