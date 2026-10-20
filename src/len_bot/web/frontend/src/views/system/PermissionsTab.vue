<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQueryClient } from '@tanstack/vue-query'
import { keys } from '../../api/query'
import type { Identities, SettingsSnapshot } from '../../api/settings'
import { systemApi, systemOf } from '../../api/system'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import FormSection from '../../ui/FormSection.vue'
import SaveBar from '../../ui/SaveBar.vue'
import Skeleton from '../../ui/Skeleton.vue'
import TagInput from '../../ui/TagInput.vue'
import { same, useSettingsDraft } from './draft'

interface Draft extends Identities {
  owners: string[]
}

const { t } = useI18n()
const client = useQueryClient()
const pick = (snapshot: SettingsSnapshot): Draft => {
  const saved = systemOf(snapshot)
  return { owners: [...saved.connection.owners], ...saved.permissions }
}
const IDENTITY = /^[a-z][a-z0-9_-]*:[^:\s/\\]+$/
const lists = ['owners', 'admins', 'whitelist', 'blacklist'] as const

const form = useSettingsDraft<Draft>({
  pick,
  section: 'permissions',
  // Owners are part of the connection settings; the other lists are saved on their own.
  save: async ({ owners, ...identities }): Promise<SettingsSnapshot> => {
    let snapshot: SettingsSnapshot = form.settings.data.value!
    const saved = systemOf(snapshot)
    if (!same(owners, saved.connection.owners)) {
      const { bot_id: _bot, telegram: _telegram, onebot, ...connection } = saved.connection
      snapshot = await systemApi.saveConnection({
        ...connection,
        owners,
        onebot: onebot && (({ access_token_configured: _configured, ...link }) => link)(onebot),
        access_token: null,
      })
      client.setQueryData(keys.host.settings(), snapshot)
    }
    if (!same(identities, saved.permissions)) snapshot = await systemApi.savePermissions(identities)
    return snapshot
  },
  // Each group's permission form sends the global lists back with its own; it must read them again.
  onSaved: () => void client.invalidateQueries({ predicate: (query) => query.queryKey[0] === 'scene' && query.queryKey[2] === 'permissions' }),
})
const { settings, draft } = form
const bot = computed(() => (settings.data.value ? systemOf(settings.data.value).connection.bot_id : ''))

const errors = computed(() => {
  const result: Record<string, string> = {}
  const value = draft.value
  if (!value) return result
  for (const list of lists) {
    const wrong = value[list].filter((item) => !IDENTITY.test(item))
    if (wrong.length) result[list] = t('system.permissions.format', { items: wrong.join(', ') })
  }
  if (value.owners.includes(bot.value)) result.owners = t('system.permissions.ownerIsBot')
  return result
})
const invalid = computed(() => Object.keys(errors.value).length > 0)
</script>

<template>
  <Skeleton v-if="settings.isPending.value" :lines="6" />
  <ErrorNote v-else-if="settings.isError.value" :title="t('system.readFailed')" :error="settings.error.value" :retry="settings.refetch" />
  <div v-else-if="draft" class="flex min-w-0 flex-col gap-4">
    <div class="flex min-w-0 flex-col gap-6 rounded-xl border border-line bg-surface p-5">
      <FormSection :title="t('system.permissions.title')" :columns="1">
        <Field v-for="list in lists" :key="list" :label="t(`system.permissions.lists.${list}`)" :error="errors[list]">
          <TagInput v-model="draft[list]" placeholder="onebot:10001" :invalid="Boolean(errors[list])" />
        </Field>
      </FormSection>
    </div>
    <SaveBar :dirty="form.dirty.value" :saving="form.saving.value" :error="form.saveError.value" :invalid="invalid" @save="form.submit" @discard="form.discard" />
  </div>
</template>
