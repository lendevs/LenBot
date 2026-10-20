<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown } from '@lucide/vue'
import type { Ability, Role, ScopedIdentities } from '../../../api/settings'
import Checkbox from '../../../ui/Checkbox.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import Input from '../../../ui/Input.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Switch from '../../../ui/Switch.vue'
import TagInput from '../../../ui/TagInput.vue'
import { useForm } from './form'

const { t } = useI18n()
const form = useForm()
const value = computed(() => form.draft.permissions)
const scoped = ref(false)

const roles: Role[] = ['owner', 'admin', 'group_manager', 'whitelist', 'member']
const abilities: Ability[] = [
  'delegate',
  'long_running',
  'task_manage',
  'own_reminder',
  'other_reminder',
  'reminder_manage',
  'chat_control',
]
const lists = ['admins', 'whitelist', 'blacklist'] as const

const ownLists = computed({
  get: () => value.value?.scene_identities !== null,
  set: (on: boolean) => {
    if (form.draft.permissions)
      form.draft.permissions.scene_identities = on ? { admins: [], whitelist: [], blacklist: [] } : null
  },
})
function allow(ability: Ability, role: Role, on: boolean | 'indeterminate') {
  const matrix = form.draft.permissions?.matrix
  if (!matrix) return
  const rest = matrix[ability].filter((item) => item !== role)
  matrix[ability] = on === true ? roles.filter((item) => item === role || rest.includes(item)) : rest
}
const scopes = ['task_identities', 'schedule_identities'] as const
function setOwner(scope: ScopedIdentities, text: string) {
  scope.owner = text.trim() || null
}
</script>

<template>
  <FormSection :title="t('groups.settings.permissions.section')" :columns="1">
    <Skeleton v-if="form.permissions.isPending" :lines="4" />
    <ErrorNote
      v-else-if="form.permissions.isError"
      :title="t('groups.settings.permissions.readFailed')"
      :error="form.permissions.error"
      :retry="form.permissions.refetch"
    />
    <template v-else-if="value">
      <p class="text-sm text-ink-2">
        {{ t('groups.settings.permissions.owners') }}
        <strong class="font-medium text-ink">
          {{ form.permissions.data?.owners.length ? form.permissions.data.owners.join(', ') : t('common.none') }}
        </strong>
      </p>

      <div class="overflow-x-auto scrollbar-thin">
        <table class="w-full min-w-[520px] text-sm">
          <caption class="sr-only">{{ t('groups.settings.permissions.matrix') }}</caption>
          <thead>
            <tr class="text-xs text-muted">
              <th scope="col" class="py-2 pr-3 text-left font-medium">{{ t('groups.settings.permissions.matrix') }}</th>
              <th v-for="role in roles" :key="role" scope="col" class="px-2 py-2 text-center font-medium">
                {{ t(`groups.settings.permissions.roles.${role}`) }}
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line border-t border-line">
            <tr v-for="ability in abilities" :key="ability">
              <th scope="row" class="py-2 pr-3 text-left font-normal text-ink">
                {{ t(`groups.settings.permissions.abilities.${ability}`) }}
              </th>
              <td v-for="role in roles" :key="role" class="px-2 py-2 text-center">
                <span class="inline-flex">
                  <Checkbox
                    :model-value="value.matrix[ability].includes(role)"
                    :aria-label="`${t(`groups.settings.permissions.abilities.${ability}`)} · ${t(`groups.settings.permissions.roles.${role}`)}`"
                    @update:model-value="(on) => allow(ability, role, on)"
                  />
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <Field :label="t('groups.settings.permissions.ownLists')" inline>
        <Switch v-model="ownLists" />
      </Field>
      <div v-if="value.scene_identities" class="grid gap-4">
        <Field v-for="list in lists" :key="list" :label="t(`groups.settings.permissions.lists.${list}`)">
          <TagInput v-model="value.scene_identities[list]" placeholder="onebot:10001" />
        </Field>
      </div>

      <div>
        <button
          type="button"
          class="inline-flex cursor-pointer items-center gap-1.5 rounded-md text-sm font-medium text-muted hover:text-ink focus-visible:focus-ring"
          :aria-expanded="scoped"
          @click="scoped = !scoped"
        >
          <ChevronDown :size="15" class="transition-transform" :class="scoped && 'rotate-180'" aria-hidden="true" />
          {{ t('groups.settings.permissions.scoped') }}
        </button>
      </div>
      <div v-if="scoped" class="grid gap-6 sm:grid-cols-2">
        <div v-for="scope in scopes" :key="scope" class="grid content-start gap-4">
          <h4 class="text-sm font-semibold text-ink">{{ t(`groups.settings.permissions.scopes.${scope}`) }}</h4>
          <Field :label="t('groups.settings.permissions.scopedOwner')">
            <Input
              :model-value="value[scope].owner ?? ''"
              placeholder="onebot:10001"
              mono
              @update:model-value="(text: string) => setOwner(value![scope], text)"
            />
          </Field>
          <Field :label="t('groups.settings.permissions.lists.admins')">
            <TagInput v-model="value[scope].admins" placeholder="onebot:10001" />
          </Field>
          <Field :label="t('groups.settings.permissions.lists.whitelist')">
            <TagInput v-model="value[scope].whitelist" placeholder="onebot:10001" />
          </Field>
        </div>
      </div>
    </template>
  </FormSection>
</template>
