<script setup lang="ts">
import { computed, provide, toRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import ErrorNote from '../../../ui/ErrorNote.vue'
import SaveBar from '../../../ui/SaveBar.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { toast } from '../../../ui/toast'
import ParticipationSection from './ParticipationSection.vue'
import FocusSection from './FocusSection.vue'
import PermissionsSection from './PermissionsSection.vue'
import PersonaSection from './PersonaSection.vue'
import PluginsSection from './PluginsSection.vue'
import ProactiveSection from './ProactiveSection.vue'
import QuietSection from './QuietSection.vue'
import RemoveSection from './RemoveSection.vue'
import RoleSection from './RoleSection.vue'
import SpeechSection from './SpeechSection.vue'
import TasksSection from './TasksSection.vue'
import { formKey, useSettingsForm } from './form'
import { confirmMemorySwitch } from './memory'

const props = defineProps<{ scene: string; timeZone: string }>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const form = useSettingsForm(toRef(props, 'scene'))
provide(formKey, form)
const group = computed(() => props.scene.split(':')[1] === 'group')
watch(
  () => form.dirty,
  (value) => emit('dirty', value),
  { immediate: true },
)

async function save() {
  if (form.memoryChanged && !(await confirmMemorySwitch())) return
  if (await form.save()) toast.success(t('common.saved'))
}
</script>

<template>
  <div class="max-w-3xl">
    <Skeleton v-if="form.settings.isPending" :lines="10" />
    <ErrorNote
      v-else-if="form.settings.isError"
      :title="t('groups.settings.readFailed')"
      :error="form.settings.error"
      :retry="form.settings.refetch"
    />
    <p v-else-if="!form.saved" class="text-sm text-muted">{{ t('groups.settings.removed') }}</p>
    <form v-else-if="form.draft" class="flex flex-col gap-8" @submit.prevent="save">
      <RoleSection :scene="scene" />
      <ParticipationSection />
      <FocusSection :scene="scene" />
      <QuietSection />
      <SpeechSection v-if="group" :scene="scene" :time-zone="timeZone" />
      <ProactiveSection v-if="group" />
      <PersonaSection />
      <TasksSection />
      <PluginsSection :scene="scene" />
      <PermissionsSection />
      <RemoveSection :scene="scene" />
      <SaveBar
        :dirty="form.dirty"
        :saving="form.saving"
        :error="form.saveError"
        :invalid="form.invalid"
        @save="save"
        @discard="form.adopt"
      />
    </form>
  </div>
</template>
