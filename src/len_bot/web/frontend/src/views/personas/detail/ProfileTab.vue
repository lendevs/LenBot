<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { PersonaRole } from '../../../api/personas'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import Input from '../../../ui/Input.vue'
import SaveBar from '../../../ui/SaveBar.vue'
import TagInput from '../../../ui/TagInput.vue'
import Textarea from '../../../ui/Textarea.vue'
import AvatarEditor from './AvatarEditor.vue'
import MoreSection from './MoreSection.vue'
import { useProfile } from './profileForm'

defineProps<{ role: PersonaRole }>()

const { t } = useI18n()
const form = useProfile()
// Folded unless the role already uses one of these, so nothing written is hidden. The tab opens after the draft.
const draft = form.draft.value
const more = ref(
  Boolean(draft && (draft.behavior.trim() || draft.aliases.length || draft.self_reference.join() !== '我')),
)
</script>

<template>
  <form v-if="form.draft.value" class="flex max-w-3xl flex-col gap-8" @submit.prevent="form.save('identity')">
    <FormSection :title="t('personas.detail.profile.who')">
      <Field wide>
        <AvatarEditor :role="role" :name="form.draft.value.name" />
      </Field>
      <Field
        :label="t('personas.detail.profile.name')"
        :error="form.draft.value.name.trim() ? null : t('personas.detail.problems.name')"
        required
        wide
      >
        <Input v-model="form.draft.value.name" class="sm:max-w-sm" />
      </Field>
    </FormSection>
    <FormSection :title="t('personas.detail.profile.character')" :columns="1">
      <Field :label="t('personas.detail.profile.brief')">
        <Textarea v-model="form.draft.value.brief" :rows="4" />
      </Field>
      <Field :label="t('personas.detail.profile.boundaries')">
        <Textarea v-model="form.draft.value.boundaries" :rows="4" />
      </Field>
    </FormSection>
    <MoreSection v-model="more" :title="t('personas.detail.more')">
      <FormSection>
        <Field :label="t('personas.detail.profile.aliases')">
          <TagInput v-model="form.draft.value.aliases" />
        </Field>
        <Field :label="t('personas.detail.profile.selfReference')">
          <TagInput
            v-model="form.draft.value.self_reference"
            :placeholder="t('personas.detail.profile.selfReferenceExample')"
          />
        </Field>
        <Field :label="t('personas.detail.profile.behavior')" wide>
          <Textarea v-model="form.draft.value.behavior" :rows="4" />
        </Field>
      </FormSection>
    </MoreSection>
    <SaveBar
      :dirty="form.dirty.value.identity"
      :saving="form.isSaving('identity')"
      :error="form.saveError('identity') ?? form.problem('identity')"
      :invalid="Boolean(form.problem('identity'))"
      @save="form.save('identity')"
      @discard="form.discard('identity')"
    />
  </form>
</template>
