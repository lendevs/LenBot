<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQueryClient } from '@tanstack/vue-query'
import { ApiError } from '../../api/client'
import { keys } from '../../api/query'
import type { SettingsSnapshot } from '../../api/settings'
import { systemApi, systemOf, type SpeechLimits } from '../../api/system'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import FormSection from '../../ui/FormSection.vue'
import Input from '../../ui/Input.vue'
import NumberInput from '../../ui/NumberInput.vue'
import SaveBar from '../../ui/SaveBar.vue'
import Skeleton from '../../ui/Skeleton.vue'
import Switch from '../../ui/Switch.vue'
import { confirm } from '../../ui/confirm'
import { toast } from '../../ui/toast'
import { copy, same, useSettingsDraft } from './draft'

interface Draft {
  speech: SpeechLimits
  groupManagers: boolean
}

const { t } = useI18n()
const client = useQueryClient()
const pick = (snapshot: SettingsSnapshot): Draft => {
  const saved = systemOf(snapshot)
  const { messages_per_hour, direct_reserve, speech_notice_text } = saved.limits
  return {
    speech: { messages_per_hour, direct_reserve, speech_notice_text },
    groupManagers: Boolean(saved.commands.group_managers_chat_reset),
  }
}
const versionOf = (snapshot: SettingsSnapshot) => (snapshot.versions as { limits?: string } | undefined)?.limits

const form = useSettingsDraft<Draft>({
  pick,
  section: 'limits',
  save: async (value): Promise<SettingsSnapshot> => {
    let snapshot: SettingsSnapshot = form.settings.data.value!
    const saved = pick(snapshot)
    if (!same(value.speech, saved.speech)) {
      try {
        snapshot = await systemApi.saveSpeech({ ...value.speech, version: base.value })
      } catch (error) {
        const latest =
          error instanceof ApiError && error.code === 'limits_conflict'
            ? (error.data as { snapshot?: SettingsSnapshot } | undefined)?.snapshot
            : undefined
        if (!latest) throw error
        // Someone saved the limits first: show what is saved now instead of overwriting it.
        client.setQueryData(keys.host.settings(), latest)
        form.draft.value = copy(pick(latest))
        // The form now matches what is saved, so the save bar closes; say why in a toast instead.
        toast.error(t('system.chat.conflict'), { duration: 12000 })
        throw error
      }
      client.setQueryData(keys.host.settings(), snapshot)
    }
    if (value.groupManagers !== saved.groupManagers) snapshot = await systemApi.saveCommands(value.groupManagers)
    return snapshot
  },
  confirm: async (value): Promise<boolean> => {
    if (!value.groupManagers || pick(form.settings.data.value!).groupManagers) return true
    return confirm({
      title: t('system.chat.managersTitle'),
      message: t('system.chat.managersMessage'),
      confirmLabel: t('common.save'),
      tone: 'danger',
    })
  },
})
const { settings, draft } = form
/** The limits version the draft started from; snapshots refreshed by events while editing do not move it. */
const base = ref<string | undefined>()
watch(
  () => [settings.data.value, form.dirty.value] as const,
  ([snapshot, dirty]) => {
    if (snapshot && !dirty) base.value = versionOf(snapshot)
  },
  { immediate: true },
)
const speech = computed(() => draft.value!.speech)

const errors = computed(() => {
  const result: Record<string, string> = {}
  const value = draft.value?.speech
  if (!value) return result
  if (value.messages_per_hour !== null && value.direct_reserve === null) result.reserve = t('system.required')
  if (value.speech_notice_text !== null && !value.speech_notice_text.trim()) result.notice = t('system.required')
  return result
})
const invalid = computed(() => Object.keys(errors.value).length > 0)
</script>

<template>
  <Skeleton v-if="settings.isPending.value" :lines="6" />
  <ErrorNote v-else-if="settings.isError.value" :title="t('system.readFailed')" :error="settings.error.value" :retry="settings.refetch" />
  <div v-else-if="draft" class="flex min-w-0 flex-col gap-4">
    <div class="flex min-w-0 flex-col gap-6 rounded-xl border border-line bg-surface p-5">
      <FormSection :title="t('system.chat.speech')">
        <Field :label="t('system.chat.limitOn')" inline wide>
          <Switch
            :model-value="speech.messages_per_hour !== null"
            @update:model-value="(on: boolean) => (speech.messages_per_hour = on ? 60 : null)"
          />
        </Field>
        <template v-if="speech.messages_per_hour !== null">
          <Field :label="t('system.chat.perHour')">
            <NumberInput v-model="speech.messages_per_hour" :min="1" />
          </Field>
          <Field :label="t('system.chat.reserve')" :error="errors.reserve">
            <NumberInput v-model="speech.direct_reserve" :min="0" />
          </Field>
          <Field :label="t('system.chat.noticeOn')" inline wide>
            <Switch
              :model-value="speech.speech_notice_text !== null"
              @update:model-value="(on: boolean) => (speech.speech_notice_text = on ? '' : null)"
            />
          </Field>
          <Field v-if="speech.speech_notice_text !== null" :label="t('system.chat.notice')" :error="errors.notice" wide>
            <Input v-model="speech.speech_notice_text" :maxlength="200" />
          </Field>
        </template>
      </FormSection>
      <FormSection :title="t('system.chat.commands')">
        <Field :label="t('system.chat.managers')" inline wide>
          <Switch v-model="draft.groupManagers" />
        </Field>
      </FormSection>
    </div>
    <SaveBar :dirty="form.dirty.value" :saving="form.saving.value" :error="form.saveError.value" :invalid="invalid" @save="form.submit" @discard="form.discard" />
  </div>
</template>
