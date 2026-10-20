<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown } from '@lucide/vue'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import NumberInput from '../../../ui/NumberInput.vue'
import Switch from '../../../ui/Switch.vue'
import { useForm } from './form'

const { t } = useI18n()
const form = useForm()
const traffic = ref(false)
const egress = ['egress_max_task_bytes', 'egress_max_daily_bytes', 'egress_bytes_per_second'] as const
</script>

<template>
  <FormSection :title="t('groups.settings.tasks.section')">
    <Field :label="t('groups.settings.tasks.reminders')" inline>
      <Switch v-model="form.draft.scene.schedules.enabled" />
    </Field>
    <Field :label="t('groups.settings.tasks.autonomous')" inline :disabled="!form.draft.scene.schedules.enabled">
      <Switch v-model="form.draft.scene.schedules.autonomous" />
    </Field>
    <Field
      :label="t('groups.settings.tasks.maxPending')"
      :error="form.errors.maxPending"
      :disabled="!form.draft.scene.schedules.enabled"
    >
      <NumberInput v-model="form.draft.scene.schedules.max_pending" :min="1" />
    </Field>
    <div class="max-sm:hidden" />
    <Field :label="t('groups.settings.tasks.tasks')" inline wide>
      <Switch v-model="form.draft.tasks.enabled" />
    </Field>
    <template v-if="form.draft.tasks.enabled">
      <Field :label="t('groups.settings.tasks.maxRunning')" :error="form.errors['tasks.max_running']">
        <NumberInput v-model="form.draft.tasks.max_running" :min="1" />
      </Field>
      <Field :label="t('groups.settings.tasks.maxDaily')" :error="form.errors['tasks.max_daily_tasks']">
        <NumberInput v-model="form.draft.tasks.max_daily_tasks" :min="1" />
      </Field>
      <div class="sm:col-span-2">
        <button
          type="button"
          class="inline-flex cursor-pointer items-center gap-1.5 rounded-md text-sm font-medium text-muted hover:text-ink focus-visible:focus-ring"
          :aria-expanded="traffic"
          @click="traffic = !traffic"
        >
          <ChevronDown :size="15" class="transition-transform" :class="traffic && 'rotate-180'" aria-hidden="true" />
          {{ t('groups.settings.tasks.traffic') }}
        </button>
      </div>
      <template v-if="traffic">
        <Field v-for="key in egress" :key="key" :label="t(`groups.settings.tasks.egress.${key}`)">
          <NumberInput
            v-model="form.draft.tasks[key]"
            :min="1"
            :steppers="false"
            :placeholder="t('groups.settings.tasks.globalValue')"
            :unit="key === 'egress_bytes_per_second' ? 'B/s' : 'B'"
          />
        </Field>
      </template>
    </template>
  </FormSection>
</template>
