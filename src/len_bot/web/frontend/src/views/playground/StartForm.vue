<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery } from '@tanstack/vue-query'
import { MessageCircle } from '@lucide/vue'
import type { HostScene } from '../../api/host'
import { personasApi } from '../../api/personas'
import { keys } from '../../api/query'
import { trialsApi, type TrialInfo } from '../../api/trials'
import { host } from '../../api/hostStore'
import { groupLabel } from '../../layouts/shell/scenes'
import Button from '../../ui/Button.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import FormSection from '../../ui/FormSection.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import Select from '../../ui/Select.vue'
import { ACTIVITY_LEVELS, type Participation } from '../../api/participation'
import ParticipationChoice from '../groups/participation/ParticipationChoice.vue'

const props = defineProps<{ scene?: string; persona?: string }>()
const emit = defineEmits<{ started: [trial: TrialInfo] }>()

const { t } = useI18n()
const scenes = computed(() => (host.state?.scenes ?? []) as HostScene[])
const roles = useQuery({
  queryKey: keys.personas.all(),
  queryFn: ({ signal }) => personasApi.library(signal),
})

/** A group's own settings and role, or another role tried in that group's settings. */
const from = ref<'group' | 'role'>(props.persona ? 'role' : 'group')
const froms = computed(() => [
  { value: 'group' as const, label: t('playground.start.fromGroup') },
  { value: 'role' as const, label: t('playground.start.fromRole') },
])
const scene = ref(
  props.scene && scenes.value.some((item) => item.scene === props.scene)
    ? props.scene
    : (scenes.value[0]?.scene ?? ''),
)
watch(
  scenes,
  (list) => {
    if (!scene.value && list[0]) scene.value = list[0].scene
  },
  { immediate: true },
)
const sceneOptions = computed(() =>
  scenes.value.map((item) => ({
    value: item.scene,
    label: `${groupLabel(item.scene)} · ${item.persona.name}`,
  })),
)
const role = ref(props.persona ?? '')
const roleOptions = computed(() =>
  (roles.data.value?.roles ?? []).map((item) => ({ value: item.key, label: item.name ?? item.key })),
)
watch(
  roleOptions,
  (list) => {
    if (!role.value && list[0]) role.value = list[0].value
  },
  { immediate: true },
)
const participation = ref<Participation>({ only_direct: true, activity: ACTIVITY_LEVELS.medium })
watch(
  scene,
  (value) => {
    const current = scenes.value.find((item) => item.scene === value)?.attention
    if (current) participation.value = { ...current }
  },
  { immediate: true },
)
const isGroup = computed(() => scene.value.split(':')[1] === 'group')
const context = ref('0')
const contexts = computed(() =>
  ['0', '20', '50', '100'].map((value) => ({
    value,
    label: value === '0' ? t('playground.start.blank') : t('playground.start.recent', { n: value }),
  })),
)

const start = useMutation({
  mutationFn: async () => {
    if (from.value === 'group')
      return trialsApi.start(scene.value, Number(context.value), participation.value)
    // The role's saved files, sent as a draft so the group keeps its own role.
    const saved = await personasApi.profile(role.value)
    const draft = await personasApi.draft(role.value, saved.directory, saved.profile)
    return trialsApi.start(scene.value, Number(context.value), participation.value, {
      directory: draft.directory,
      files: draft.files,
    })
  },
  onSuccess: (trial) => emit('started', trial),
})
const ready = computed(() => Boolean(scene.value) && (from.value === 'group' || Boolean(role.value)))
</script>

<template>
  <form
    class="flex max-w-3xl flex-col gap-5 rounded-xl border border-line bg-surface p-5"
    @submit.prevent="start.mutate()"
  >
    <FormSection :title="t('playground.start.title')">
      <Field :label="t('playground.start.from')" wide>
        <div><SegmentedControl v-model="from" :options="froms" :label="t('playground.start.from')" /></div>
      </Field>
      <Field :label="from === 'group' ? t('playground.start.group') : t('playground.start.groupFor')">
        <Select
          v-model="scene"
          :options="sceneOptions"
          :placeholder="t('playground.start.noGroups')"
          :disabled="!sceneOptions.length"
        />
      </Field>
      <Field v-if="from === 'role'" :label="t('playground.start.role')">
        <Select v-model="role" :options="roleOptions" :disabled="!roleOptions.length" />
      </Field>
      <Field :label="t('playground.start.context')">
        <Select v-model="context" :options="contexts" />
      </Field>
      <ParticipationChoice v-if="isGroup" v-model="participation" />
    </FormSection>
    <ErrorNote v-if="start.isError.value" :title="t('playground.start.failed')" :error="start.error.value" />
    <div>
      <Button
        type="submit"
        variant="primary"
        :icon="MessageCircle"
        :loading="start.isPending.value"
        :disabled="!ready"
      >
        {{ t('playground.start.submit') }}
      </Button>
    </div>
  </form>
</template>
