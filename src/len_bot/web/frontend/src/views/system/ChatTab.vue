<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQueryClient } from '@tanstack/vue-query'
import { ApiError } from '../../api/client'
import { keys } from '../../api/query'
import type { SettingsSnapshot } from '../../api/settings'
import { systemApi, systemOf, type SpeechLimits } from '../../api/system'
import Button from '../../ui/Button.vue'
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

const emit = defineEmits<{ dirty: [value: boolean] }>()

interface Draft {
  speech: SpeechLimits
  groupManagers: boolean
}

const { t } = useI18n()
const client = useQueryClient()
const stashed = ref<Draft | null>(null)
const noticeTouched = ref(false)

const pick = (snapshot: SettingsSnapshot): Draft => {
  const saved = systemOf(snapshot)
  const { messages_per_hour, direct_reserve, speech_notice_text } = saved.limits
  return {
    speech: { messages_per_hour, direct_reserve, speech_notice_text },
    groupManagers: Boolean(saved.commands.group_managers_chat_reset),
  }
}
const versionOf = (snapshot: SettingsSnapshot) =>
  (snapshot.versions as { limits?: string } | undefined)?.limits

const form = useSettingsDraft<Draft>({
  pick,
  section: 'limits',
  reset: () => {
    stashed.value = null
    noticeTouched.value = false
  },
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
        // Someone saved the limits first: keep the user's edits aside so they can reapply on top of latest.
        stashed.value = copy(value)
        client.setQueryData(keys.host.settings(), latest)
        form.draft.value = copy(pick(latest))
        noticeTouched.value = false
        toast.error(t('system.chat.conflict'), { duration: 12000 })
        throw error
      }
      client.setQueryData(keys.host.settings(), snapshot)
    }
    if (value.groupManagers !== saved.groupManagers)
      snapshot = await systemApi.saveCommands(value.groupManagers)
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
watch(form.dirty, (dirty) => emit('dirty', dirty), { immediate: true })

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

function toggleNotice(on: boolean) {
  if (!draft.value) return
  noticeTouched.value = false
  draft.value.speech.speech_notice_text = on ? '' : null
}

function reapplyStashed() {
  if (!stashed.value) return
  draft.value = copy(stashed.value)
  stashed.value = null
  noticeTouched.value = false
}

const noticeEmpty = computed(() =>
  Boolean(
    draft.value &&
    draft.value.speech.messages_per_hour !== null &&
    draft.value.speech.speech_notice_text !== null &&
    !draft.value.speech.speech_notice_text.trim(),
  ),
)
const errors = computed(() => {
  const result: Record<string, string> = {}
  const value = draft.value?.speech
  if (!value) return result
  if (value.messages_per_hour !== null && value.direct_reserve === null) result.reserve = t('system.required')
  if (noticeEmpty.value && noticeTouched.value) result.notice = t('system.required')
  return result
})
const invalid = computed(() => Object.keys(errors.value).length > 0 || noticeEmpty.value)
</script>

<template>
  <Skeleton v-if="settings.isPending.value" :lines="6" />
  <ErrorNote
    v-else-if="settings.isError.value"
    :title="t('system.readFailed')"
    :error="settings.error.value"
    :retry="settings.refetch"
  />
  <div v-else-if="draft" class="flex min-w-0 max-w-3xl flex-col gap-4">
    <div
      v-if="stashed"
      role="status"
      class="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-warning-bg px-3.5 py-2.5 text-sm text-warning"
    >
      <span class="min-w-0 flex-1">{{ t('system.chat.conflict') }}</span>
      <Button size="sm" variant="ghost" @click="reapplyStashed">
        {{ t('system.chat.reapply') }}
      </Button>
    </div>
    <div class="flex min-w-0 flex-col gap-6">
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
            <Switch :model-value="speech.speech_notice_text !== null" @update:model-value="toggleNotice" />
          </Field>
          <Field
            v-if="speech.speech_notice_text !== null"
            :label="t('system.chat.notice')"
            :error="errors.notice"
            wide
          >
            <Input
              v-model="speech.speech_notice_text"
              :maxlength="200"
              @update:model-value="noticeTouched = true"
              @blur="noticeTouched = true"
            />
          </Field>
        </template>
      </FormSection>
      <FormSection :title="t('system.chat.commands')">
        <Field :label="t('system.chat.managers')" inline wide>
          <Switch v-model="draft.groupManagers" />
        </Field>
      </FormSection>
    </div>
    <SaveBar
      :dirty="form.dirty.value"
      :saving="form.saving.value"
      :error="form.saveError.value"
      :invalid="invalid"
      :action-label="stashed ? t('system.chat.reapply') : undefined"
      @save="form.submit"
      @discard="form.discard"
      @action="reapplyStashed"
    />
  </div>
</template>
