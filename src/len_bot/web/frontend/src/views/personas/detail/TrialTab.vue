<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { ArrowUpRight, MessageCircle, Square } from '@lucide/vue'
import type { HostScene } from '../../../api/host'
import { personasApi, type PersonaRole, type Trial } from '../../../api/personas'
import ChatPanel from '../../../host/components/ChatPanel.vue'
import { host } from '../../../host/store.js'
import { groupLabel } from '../../../layouts/shell/scenes'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import Select from '../../../ui/Select.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import { useProfile } from './profileForm'

const props = defineProps<{ role: PersonaRole }>()

const { t } = useI18n()
const form = useProfile()
const scenes = computed(() => (host.state?.scenes ?? []) as HostScene[])
const scene = ref(props.role.scenes[0] ?? scenes.value[0]?.scene ?? '')
const sceneOptions = computed(() => scenes.value.map((item) => ({ value: item.scene, label: groupLabel(item.scene) })))
const context = ref('0')
const contextOptions = computed(() =>
  ['0', '20', '50', '100'].map((value) => ({
    value,
    label: value === '0' ? t('personas.detail.trial.blank') : t('personas.detail.trial.recent', { n: value }),
  })),
)
const unsaved = computed(() => form.dirty.value.identity || form.dirty.value.speech)
const problem = computed(() => form.problem('identity') ?? form.problem('speech'))

const trial = ref<Trial | null>(null)
const start = useMutation({
  mutationFn: async () => personasApi.trial(scene.value, Number(context.value), await form.draftFiles()),
  onSuccess: (value) => (trial.value = value),
})
const stop = useMutation({
  mutationFn: (id: string) => personasApi.stopTrial(id),
  onSuccess: () => (trial.value = null),
  onError: (error) =>
    toast.error(t('personas.detail.trial.stopFailed'), { detail: describeError(error, t('ui.error.network')).message }),
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
  <EmptyState v-if="!scenes.length" :icon="MessageCircle" :title="t('groups.empty')" />
  <div v-else-if="trial" class="flex min-w-0 flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <h3 class="min-w-0 flex-1 truncate text-base font-semibold">
        {{ t('personas.detail.trial.running', { name: trial.persona, group: groupLabel(trial.scene) }) }}
      </h3>
      <Button size="sm" variant="ghost" :icon-right="ArrowUpRight" :to="{ name: 'host-trials', query: { trial: trial.id } }">
        {{ t('personas.detail.trial.openPlayground') }}
      </Button>
      <Button size="sm" :icon="Square" :loading="stop.isPending.value" @click="end">{{ t('personas.detail.trial.stop') }}</Button>
    </div>
    <ChatPanel :key="trial.id" :api-base="`/api/host/trials/${encodeURIComponent(trial.id)}`" />
  </div>
  <form v-else class="flex max-w-3xl flex-col gap-6" @submit.prevent="start.mutate()">
    <FormSection :title="t('personas.detail.trial.title')">
      <template #actions>
        <Badge v-if="unsaved" tone="warning">{{ t('personas.detail.trial.unsaved') }}</Badge>
      </template>
      <Field :label="t('personas.detail.trial.group')">
        <Select v-model="scene" :options="sceneOptions" />
      </Field>
      <Field :label="t('personas.detail.trial.context')">
        <Select v-model="context" :options="contextOptions" />
      </Field>
    </FormSection>
    <p v-if="problem" class="text-sm text-error">{{ problem }}</p>
    <ErrorNote v-if="start.isError.value" :title="t('personas.detail.trial.startFailed')" :error="start.error.value" />
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
