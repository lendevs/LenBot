<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessageCircle } from '@lucide/vue'
import type { HostScene } from '../../../api/host'
import type { PersonaRole } from '../../../api/personas'
import { host } from '../../../api/hostStore'
import { groupLabel, groupSecondaryId } from '../../../layouts/shell/scenes'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Select from '../../../ui/Select.vue'
import PreviewPanel from './PreviewPanel.vue'
import TrialPanel from './TrialPanel.vue'
import { useProfile } from './profileForm'

/** `others` names the other tabs holding unsaved edits; trial and preview use only the profile form. */
const props = defineProps<{ role: PersonaRole; others: string[] }>()
const emit = defineEmits<{ jump: [tab: 'profile' | 'speech'] }>()

const { t } = useI18n()
const sceneFieldId = useId()
const form = useProfile()
const mode = ref<'trial' | 'preview'>('trial')
const modes = computed(() => [
  { value: 'trial' as const, label: t('personas.detail.effect.trial') },
  { value: 'preview' as const, label: t('personas.detail.effect.preview') },
])

/** Select options cannot be empty; this stands for the role without any group's settings. */
const NONE = '*'
const groupOptionLabel = (value: string) => {
  const name = groupLabel(value)
  const id = groupSecondaryId(value)
  return id ? `${name} (${id})` : name
}
const scenes = computed(() => (host.state?.scenes ?? []) as HostScene[])
const fallback = () =>
  props.role.scenes.find((scene) => scenes.value.some((item) => item.scene === scene)) ??
  scenes.value[0]?.scene ??
  NONE
const scene = ref(fallback())
const options = computed(() => [
  ...scenes.value.map((item) => ({ value: item.scene, label: groupOptionLabel(item.scene) })),
  ...(mode.value === 'preview' ? [{ value: NONE, label: t('personas.detail.preview.noScene') }] : []),
])
watch(options, (value) => {
  if (!value.some((option) => option.value === scene.value)) scene.value = fallback()
})

const unsaved = computed(() => form.dirty.value.identity || form.dirty.value.speech)
const identityProblem = computed(() => form.problem('identity'))
const speechProblem = computed(() => form.problem('speech'))
const problem = computed(() => identityProblem.value ?? speechProblem.value)
const problemTab = computed<'profile' | 'speech' | null>(() =>
  identityProblem.value ? 'profile' : speechProblem.value ? 'speech' : null,
)
const excluded = computed(() =>
  props.others.map((name) => t(`personas.detail.tabs.${name}`)).join(t('personas.separator')),
)
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <div class="flex flex-wrap items-center gap-3 border-b border-line pb-4">
      <SegmentedControl v-model="mode" :options="modes" :label="t('personas.detail.tabs.effect')" />
      <div v-if="options.length" class="flex min-w-0 items-center gap-2 max-sm:w-full">
        <label :for="sceneFieldId" class="shrink-0 text-sm font-medium text-ink-2">
          {{ t('personas.detail.effect.scene') }}
        </label>
        <div class="min-w-0 flex-1 tabular sm:w-64">
          <Select :id="sceneFieldId" v-model="scene" :options="options" size="sm" />
        </div>
      </div>
      <div v-if="unsaved || others.length" class="flex flex-wrap items-center gap-2">
        <Badge v-if="unsaved" tone="warning">{{ t('personas.detail.effect.unsaved') }}</Badge>
        <Badge v-if="others.length">{{ t('personas.detail.effect.excluded', { names: excluded }) }}</Badge>
      </div>
    </div>
    <div
      v-if="problem && mode !== 'preview'"
      class="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-error-bg px-3.5 py-2.5 text-sm text-error"
    >
      <span>{{ problem }}</span>
      <Button v-if="problemTab" size="sm" variant="ghost" @click="emit('jump', problemTab)">
        {{ t('personas.detail.preview.fixIn', { tab: t(`personas.detail.tabs.${problemTab}`) }) }}
      </Button>
    </div>
    <EmptyState v-if="mode === 'trial' && !scenes.length" :icon="MessageCircle" :title="t('groups.empty')" />
    <KeepAlive v-else>
      <PreviewPanel
        v-if="mode === 'preview'"
        :role="role"
        :scene="scene === NONE ? null : scene"
        @jump="emit('jump', $event)"
      />
      <TrialPanel v-else :role="role" :scene="scene === NONE ? '' : scene" />
    </KeepAlive>
  </div>
</template>
