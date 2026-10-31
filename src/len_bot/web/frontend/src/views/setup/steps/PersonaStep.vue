<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Combobox from '../../../ui/Combobox.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import RadioGroup from '../../../ui/RadioGroup.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import Textarea from '../../../ui/Textarea.vue'
import ParticipationChoice from '../../groups/participation/ParticipationChoice.vue'
import MoreFields from '../MoreFields.vue'
import { personaFolder, useStepErrors, useWizard } from '../wizard'

const { t } = useI18n()
const wizard = useWizard()
const { draft } = wizard
const error = useStepErrors('persona')

const templates = computed(() => [
  { value: 'companion' as const, label: t('setup.persona.companion') },
  { value: 'custom' as const, label: t('setup.persona.custom') },
])
const kinds = computed(() => [
  { value: 'group' as const, label: t('setup.persona.group') },
  { value: 'private' as const, label: t('setup.persona.private') },
])
const groups = computed(() =>
  draft.sceneKind === 'group'
    ? wizard.joinedGroups.value.map((group) => ({ value: group.id, label: group.name, meta: group.id }))
    : [],
)
const sources = computed(() => [
  { value: 'list' as const, label: t('setup.persona.fromList') },
  { value: 'manual' as const, label: t('setup.persona.manual') },
])
/** The group list only when the connection gave one; with no connection the number is typed. */
const listed = computed(() => groups.value.length > 0 && draft.groupSource === 'list')
const chosen = computed({
  get: () => draft.sceneId || undefined,
  set: (value: string | string[] | undefined) => (draft.sceneId = typeof value === 'string' ? value : ''),
})
const more = ref(false)
watch(
  () => error('personaId'),
  (wrong) => wrong && (more.value = true),
  { immediate: true },
)
</script>

<template>
  <div class="flex flex-col gap-6">
    <Field :label="t('setup.persona.template')">
      <RadioGroup v-model="draft.persona" :options="templates" />
    </Field>
    <div v-if="draft.persona === 'custom'" class="grid animate-rise gap-x-5 gap-y-5 sm:grid-cols-2">
      <Field :label="t('setup.persona.name')" :error="error('personaName')" required>
        <Input v-model="draft.personaName" />
      </Field>
      <Field :label="t('setup.persona.brief')" :error="error('brief')" required wide>
        <Textarea v-model="draft.brief" :placeholder="t('setup.persona.briefPlaceholder')" />
      </Field>
      <Field :label="t('setup.persona.voice')" :error="error('voice')" wide>
        <Textarea v-model="draft.voice" :placeholder="t('setup.persona.voicePlaceholder')" />
      </Field>
      <Field :label="t('setup.persona.boundaries')" wide>
        <Textarea
          v-model="draft.boundaries"
          :rows="2"
          :placeholder="t('setup.persona.boundariesPlaceholder')"
        />
      </Field>
    </div>
    <div class="grid gap-x-5 gap-y-5 border-t border-line pt-6 sm:grid-cols-2">
      <Field :label="t('setup.persona.where')">
        <div>
          <SegmentedControl v-model="draft.sceneKind" :options="kinds" :label="t('setup.persona.where')" />
        </div>
      </Field>
      <Field v-if="groups.length" :label="t('setup.persona.groupSource')">
        <div>
          <SegmentedControl
            v-model="draft.groupSource"
            :options="sources"
            :label="t('setup.persona.groupSource')"
          />
        </div>
      </Field>
      <Field
        :label="draft.sceneKind === 'group' ? t('setup.persona.groupId') : t('setup.persona.privateId')"
        :error="error('sceneId')"
        required
      >
        <Combobox v-if="listed" v-model="chosen" :options="groups" />
        <Input v-else v-model="draft.sceneId" mono inputmode="numeric" />
      </Field>
      <ParticipationChoice v-if="draft.sceneKind === 'group'" v-model="draft.participation" />
    </div>
    <MoreFields v-if="draft.persona === 'custom'" v-model="more" :title="t('setup.persona.more')">
      <Field :label="t('setup.persona.id')" :error="error('personaId')">
        <Input v-model.trim="draft.personaId" mono :placeholder="personaFolder(draft.personaName)" />
      </Field>
    </MoreFields>
  </div>
</template>
