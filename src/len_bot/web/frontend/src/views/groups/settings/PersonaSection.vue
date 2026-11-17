<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, Trash2 } from '@lucide/vue'
import Button from '../../../ui/Button.vue'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import IconButton from '../../../ui/IconButton.vue'
import Input from '../../../ui/Input.vue'
import TagInput from '../../../ui/TagInput.vue'
import Textarea from '../../../ui/Textarea.vue'
import { useForm } from './form'

const { t } = useI18n()
const form = useForm()
const addendum = computed({
  get: () => form.draft.scene.behavior_addendum ?? '',
  set: (value: string) => (form.draft.scene.behavior_addendum = value || null),
})
</script>

<template>
  <FormSection :title="t('groups.settings.persona.section')" :columns="1">
    <Field :label="t('groups.settings.persona.aliases')" :error="form.errors.aliases">
      <TagInput v-model="form.draft.scene.persona_aliases" />
    </Field>
    <Field :label="t('groups.settings.persona.relationships')">
      <div class="flex flex-col gap-2.5">
        <div
          v-if="form.draft.relationships.length"
          class="flex flex-col divide-y divide-line sm:gap-2 sm:divide-y-0"
        >
          <div
            v-for="(row, index) in form.draft.relationships"
            :key="index"
            class="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 py-3 first:pt-0 last:pb-0 sm:grid-cols-[180px_minmax(0,1fr)_auto] sm:py-0"
          >
            <div class="min-w-0">
              <Field :error="form.errors[`relationships.${index}.account`]">
                <Input
                  v-model="row.account"
                  placeholder="onebot:10001"
                  mono
                  :aria-label="t('groups.settings.persona.account')"
                />
              </Field>
            </div>
            <div class="min-w-0 max-sm:order-3 max-sm:col-span-2">
              <Field :error="form.errors[`relationships.${index}.text`]">
                <Input v-model="row.text" :aria-label="t('groups.settings.persona.relationship')" />
              </Field>
            </div>
            <div class="pt-0.5 sm:order-3">
              <IconButton
                :icon="Trash2"
                :label="t('common.delete')"
                variant="danger-ghost"
                @click="form.draft.relationships.splice(index, 1)"
              />
            </div>
          </div>
        </div>
        <div>
          <Button
            size="sm"
            variant="ghost"
            :icon="Plus"
            @click="form.draft.relationships.push({ account: '', text: '' })"
          >
            {{ t('groups.settings.persona.add') }}
          </Button>
        </div>
      </div>
    </Field>
    <Field :label="t('groups.settings.persona.addendum')">
      <Textarea v-model="addendum" :rows="2" />
    </Field>
  </FormSection>
</template>
