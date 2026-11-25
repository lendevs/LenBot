<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { ArrowUpRight, MessageCircle, RotateCcw, Square } from '@lucide/vue'
import type { HostScene } from '../../../api/host'
import { host } from '../../../api/hostStore'
import { DEFAULT_PARTICIPATION, type Participation } from '../../../api/participation'
import { personasApi, type PersonaRole, type Trial } from '../../../api/personas'
import { keys } from '../../../api/query'
import { trialSource, trialsApi, type TrialInfo } from '../../../api/trials'
import ChatPanel from '../../playground/chat/ChatPanel.vue'
import ParticipationChoice from '../../groups/participation/ParticipationChoice.vue'
import { groupLabel, groupSecondaryId } from '../../../layouts/shell/scenes'
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

const props = defineProps<{ role: PersonaRole; scene: string }>()

const { t } = useI18n()
const client = useQueryClient()
const form = useProfile()
const scenes = computed(() => (host.state?.scenes ?? []) as HostScene[])

const context = ref('0')
const contextOptions = computed(() =>
  ['0', '20', '50', '100'].map((value) => ({
    value,
    label: value === '0' ? t('personas.detail.trial.blank') : t('personas.detail.trial.recent', { n: value }),
  })),
)
const participation = ref<Participation>({ ...DEFAULT_PARTICIPATION })
watch(
  () => props.scene,
  (value) => {
    const current = scenes.value.find((item) => item.scene === value)?.attention
    if (current) participation.value = { ...current }
  },
  { immediate: true },
)
const isGroup = computed(() => props.scene.split(':')[1] === 'group')

const problem = computed(() => form.problem('identity') ?? form.problem('speech'))
const current = () => JSON.stringify(form.draft.value)

const trial = ref<Trial | null>(null)
const otherActive = ref<TrialInfo | null>(null)
/** The draft the running trial started from; later edits show as a change until it restarts. */
const started = ref('')
const draftChanged = computed(() => trial.value !== null && current() !== started.value)
const sceneChanged = computed(
  () => trial.value !== null && Boolean(props.scene) && props.scene !== trial.value.scene,
)
const changed = computed(() => draftChanged.value || sceneChanged.value)
const listError = ref<unknown>(null)
let mounted = true
onBeforeUnmount(() => (mounted = false))

// The host keeps one trial running; pick up this role's draft trial or surface any other active trial.
async function loadRunning() {
  listError.value = null
  const directory = form.saved.data.value?.directory
  if (!directory) return
  try {
    const items = (await trialsApi.list()).items
    if (!mounted) return
    if (trial.value) {
      const stillRunning = items.find((item) => item.id === trial.value!.id && item.active)
      if (!stillRunning) trial.value = null
    }
    const running = items.find((item) => item.active) ?? null
    if (!running) {
      otherActive.value = null
      return
    }
    if (running.draft_source === directory) {
      otherActive.value = null
      if (!trial.value) {
        started.value = current()
        trial.value = running
      }
    } else {
      otherActive.value = running
    }
  } catch (error) {
    if (mounted) listError.value = error
  }
}
onMounted(() => void loadRunning())
onActivated(() => void loadRunning())

function participationLabel(attention: Participation) {
  if (attention.only_direct) return t('participation.short.direct')
  return t('participation.short.join', {
    level: attention.level ? t(`participation.levels.${attention.level}`) : t('participation.custom'),
  })
}

async function launch(scene: string) {
  const snapshot = current()
  const attention = scene.split(':')[1] === 'group' ? participation.value : undefined
  const value = await personasApi.trial(scene, Number(context.value), await form.draftFiles(), attention)
  started.value = snapshot
  return value
}
const start = useMutation({
  mutationFn: launch,
  onSuccess: (value) => {
    listError.value = null
    otherActive.value = null
    trial.value = value
    void client.invalidateQueries({ queryKey: keys.trials() })
  },
  onError: (error) => {
    if (describeError(error, t('ui.error.network')).status === 409) {
      void loadRunning()
    }
  },
})
const stopAndStart = useMutation({
  mutationFn: async (scene: string) => {
    let activeId = otherActive.value?.id
    if (!activeId) {
      activeId = (await trialsApi.list()).items.find((item) => item.active)?.id
    }
    if (activeId) {
      await personasApi.stopTrial(activeId)
      void client.invalidateQueries({ queryKey: keys.chat.all(trialSource(activeId).id) })
    }
    otherActive.value = null
    return launch(scene)
  },
  onSuccess: (value) => {
    listError.value = null
    start.reset()
    trial.value = value
    void client.invalidateQueries({ queryKey: keys.trials() })
  },
  onSettled: () => void client.invalidateQueries({ queryKey: keys.trials() }),
})
const restart = useMutation({
  mutationFn: async ({ id, scene }: { id: string; scene: string }) => {
    await personasApi.stopTrial(id)
    trial.value = null
    void client.invalidateQueries({ queryKey: keys.chat.all(trialSource(id).id) })
    return launch(scene)
  },
  onSuccess: (value) => {
    otherActive.value = null
    trial.value = value
  },
  onError: (error) =>
    toast.error(t('personas.detail.trial.restartFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
  onSettled: () => void client.invalidateQueries({ queryKey: keys.trials() }),
})
const stop = useMutation({
  mutationFn: (id: string) => personasApi.stopTrial(id),
  onSuccess: (_, id) => {
    trial.value = null
    void client.invalidateQueries({ queryKey: keys.chat.all(trialSource(id).id) })
    void client.invalidateQueries({ queryKey: keys.trials() })
  },
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
const canLaunch = computed(() => Boolean(props.scene) && !problem.value && Boolean(form.draft.value))
const startError = computed(() =>
  stopAndStart.isError.value
    ? stopAndStart.error.value
    : start.isError.value && !otherActive.value
      ? start.error.value
      : null,
)
</script>

<template>
  <div v-if="trial" class="flex min-w-0 flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2 border-b border-line pb-3">
      <div class="flex min-w-0 flex-1 flex-wrap items-baseline gap-2">
        <h3 class="min-w-0 truncate text-base font-semibold text-ink">
          {{ t('personas.detail.trial.running', { name: trial.persona, group: groupLabel(trial.scene) }) }}
        </h3>
        <span v-if="groupSecondaryId(trial.scene)" class="shrink-0 font-mono text-xs text-subtle tabular">
          {{ groupSecondaryId(trial.scene) }}
        </span>
      </div>
      <Badge v-if="trial.memory_plugin">
        {{ t('playground.nativeMemory', { name: trial.memory_plugin }) }}
      </Badge>
      <Badge v-if="trial.attention && trial.scene.split(':')[1] === 'group'">
        {{ participationLabel(trial.attention) }}
      </Badge>
      <Badge v-if="changed" tone="warning">
        {{ draftChanged ? t('personas.detail.trial.changed') : t('personas.detail.trial.sceneChanged') }}
      </Badge>
      <div class="flex flex-wrap items-center gap-2">
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
    </div>
    <ChatPanel :key="trial.id" :source="trialSource(trial.id)" :context="trial.context" embedded />
  </div>
  <form
    v-else
    class="flex max-w-2xl flex-col gap-6"
    @submit.prevent="canLaunch && (otherActive ? stopAndStart.mutate(scene) : start.mutate(scene))"
  >
    <div
      v-if="otherActive"
      role="status"
      class="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-warning-bg px-3.5 py-2.5 text-sm text-warning"
    >
      <span class="min-w-0 flex-1">
        {{
          t('personas.detail.trial.otherRunning', {
            name: otherActive.persona,
            group: groupLabel(otherActive.scene),
          })
        }}
      </span>
      <div class="flex shrink-0 flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="ghost"
          :icon-right="ArrowUpRight"
          :to="{ name: 'host-trials', query: { trial: otherActive.id } }"
        >
          {{ t('personas.detail.trial.openPlayground') }}
        </Button>
        <Button
          size="sm"
          variant="primary"
          :loading="stopAndStart.isPending.value"
          :disabled="!canLaunch || start.isPending.value"
          @click="stopAndStart.mutate(scene)"
        >
          {{ t('personas.detail.trial.stopAndStart') }}
        </Button>
      </div>
    </div>
    <FormSection :title="t('personas.detail.trial.title')">
      <Field :label="t('personas.detail.trial.context')">
        <Select v-model="context" :options="contextOptions" />
      </Field>
      <ParticipationChoice v-if="isGroup" v-model="participation" />
    </FormSection>
    <ErrorNote
      v-if="listError"
      :title="t('personas.detail.trial.readFailed')"
      :error="listError"
      :retry="loadRunning"
    />
    <ErrorNote v-if="startError" :title="t('personas.detail.trial.startFailed')" :error="startError" />
    <div v-if="!otherActive">
      <Button
        type="submit"
        variant="primary"
        :icon="MessageCircle"
        :loading="start.isPending.value"
        :disabled="!canLaunch"
      >
        {{ t('personas.detail.trial.start') }}
      </Button>
    </div>
  </form>
</template>
