<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Ability, Role, ScopedIdentities } from '../../../api/settings'
import Checkbox from '../../../ui/Checkbox.vue'
import Collapsible from '../../../ui/Collapsible.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import Input from '../../../ui/Input.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Switch from '../../../ui/Switch.vue'
import TagInput from '../../../ui/TagInput.vue'
import { cloneValue, useForm, withPlatform } from './form'

const { t } = useI18n()
const form = useForm()
const value = computed(() => form.draft.permissions)

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
const scopes = ['task_identities', 'schedule_identities'] as const

const tableWrap = ref<HTMLDivElement | null>(null)
const scrolledX = ref(false)
function onTableScroll() {
  scrolledX.value = (tableWrap.value?.scrollLeft ?? 0) > 0
}

const ownLists = computed({
  get: () => value.value?.scene_identities !== null,
  set: (on: boolean) => {
    if (!form.draft.permissions) return
    if (!on) {
      form.draft.permissions.scene_identities = null
      return
    }
    const saved = form.saved?.permissions?.scene_identities
    form.draft.permissions.scene_identities = saved
      ? cloneValue(saved)
      : { admins: [], whitelist: [], blacklist: [] }
  },
})

function allow(ability: Ability, role: Role, on: boolean | 'indeterminate') {
  const matrix = form.draft.permissions?.matrix
  if (!matrix) return
  const rest = matrix[ability].filter((item) => item !== role)
  matrix[ability] = on === true ? roles.filter((item) => item === role || rest.includes(item)) : rest
}
function toggleCell(ability: Ability, role: Role, event: MouseEvent) {
  if ((event.target as HTMLElement | null)?.closest('label, button')) return
  const matrix = form.draft.permissions?.matrix
  if (!matrix) return
  allow(ability, role, !matrix[ability].includes(role))
}

function normalizeList(items: string[]): string[] {
  return items.map((item) => withPlatform(form.scene, item))
}
function setSceneList(list: (typeof lists)[number], items: string[]) {
  if (form.draft.permissions?.scene_identities) {
    form.draft.permissions.scene_identities[list] = normalizeList(items)
  }
}
function setScopedList(scope: (typeof scopes)[number], list: 'admins' | 'whitelist', items: string[]) {
  if (form.draft.permissions) {
    form.draft.permissions[scope][list] = normalizeList(items)
  }
}
function setOwner(scope: ScopedIdentities, text: string) {
  scope.owner = text.trim() || null
}
function normalizeOwner(scope: ScopedIdentities) {
  if (scope.owner) scope.owner = withPlatform(form.scene, scope.owner)
}

const hasScopedError = computed(() =>
  scopes.some(
    (scope) =>
      Boolean(form.errors[`permissions.${scope}.owner`]) ||
      Boolean(form.errors[`permissions.${scope}.admins`]) ||
      Boolean(form.errors[`permissions.${scope}.whitelist`]),
  ),
)
</script>

<template>
  <FormSection id="permissions" :title="t('groups.settings.permissions.section')" :columns="1">
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
        <strong
          class="font-medium text-ink tabular"
          :class="(form.permissions.data?.owners.length ?? 0) > 0 && 'font-mono text-xs'"
        >
          {{
            form.permissions.data?.owners.length ? form.permissions.data.owners.join(', ') : t('common.none')
          }}
        </strong>
      </p>

      <div ref="tableWrap" class="-mx-1 min-w-0 overflow-x-auto px-1 scrollbar-thin" @scroll="onTableScroll">
        <table class="w-full border-collapse text-sm">
          <caption class="sr-only">{{ t('groups.settings.permissions.matrix') }}</caption>
          <thead>
            <tr class="text-xs text-muted">
              <th
                scope="col"
                class="sticky left-0 z-1 bg-page py-2 pr-2 text-left font-medium transition-colors sm:pr-3"
                :class="scrolledX && 'border-r border-line'"
              >
                {{ t('groups.settings.permissions.matrix') }}
              </th>
              <th
                v-for="role in roles"
                :key="role"
                scope="col"
                class="px-1.5 py-2 text-center font-medium whitespace-nowrap sm:px-2.5"
              >
                {{ t(`groups.settings.permissions.roles.${role}`) }}
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line border-t border-line">
            <tr v-for="ability in abilities" :key="ability" class="group transition-colors hover:bg-hover">
              <th
                scope="row"
                class="sticky left-0 z-1 min-w-28 bg-page py-2 pr-2 text-left font-normal text-ink transition-colors group-hover:bg-hover sm:pr-3"
                :class="scrolledX && 'border-r border-line'"
              >
                {{ t(`groups.settings.permissions.abilities.${ability}`) }}
              </th>
              <td v-for="role in roles" :key="role" class="p-0 text-center">
                <div
                  class="flex min-h-10 w-full cursor-pointer items-center justify-center px-1.5 py-2 sm:px-2.5"
                  @click="toggleCell(ability, role, $event)"
                >
                  <Checkbox
                    :model-value="value.matrix[ability].includes(role)"
                    :aria-label="`${t(`groups.settings.permissions.abilities.${ability}`)} · ${t(`groups.settings.permissions.roles.${role}`)}`"
                    @update:model-value="(on) => allow(ability, role, on)"
                  />
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <Field :label="t('groups.settings.permissions.ownLists')" inline>
        <Switch v-model="ownLists" />
      </Field>
      <div v-if="value.scene_identities" class="grid animate-fade gap-4 border-t border-line pt-4">
        <Field
          v-for="list in lists"
          :key="list"
          :label="t(`groups.settings.permissions.lists.${list}`)"
          :error="form.errors[`permissions.scene.${list}`]"
        >
          <TagInput
            :model-value="value.scene_identities[list]"
            placeholder="onebot:10001"
            @update:model-value="(items: string[]) => setSceneList(list, items)"
          />
        </Field>
      </div>

      <Collapsible
        v-model:open="form.expanded.permissionsScoped"
        :title="t('groups.settings.permissions.scoped')"
        :dot="hasScopedError ? 'error' : false"
        content-class="grid gap-6 sm:grid-cols-2"
      >
        <div v-for="scope in scopes" :key="scope" class="grid content-start gap-4">
          <h4 class="text-sm font-semibold text-ink">
            {{ t(`groups.settings.permissions.scopes.${scope}`) }}
          </h4>
          <Field
            :label="t('groups.settings.permissions.scopedOwner')"
            :error="form.errors[`permissions.${scope}.owner`]"
          >
            <Input
              :model-value="value[scope].owner ?? ''"
              placeholder="onebot:10001"
              mono
              @update:model-value="(text: string) => setOwner(value![scope], text)"
              @blur="normalizeOwner(value![scope])"
            />
          </Field>
          <Field
            :label="t('groups.settings.permissions.lists.admins')"
            :error="form.errors[`permissions.${scope}.admins`]"
          >
            <TagInput
              :model-value="value[scope].admins"
              placeholder="onebot:10001"
              @update:model-value="(items: string[]) => setScopedList(scope, 'admins', items)"
            />
          </Field>
          <Field
            :label="t('groups.settings.permissions.lists.whitelist')"
            :error="form.errors[`permissions.${scope}.whitelist`]"
          >
            <TagInput
              :model-value="value[scope].whitelist"
              placeholder="onebot:10001"
              @update:model-value="(items: string[]) => setScopedList(scope, 'whitelist', items)"
            />
          </Field>
        </div>
      </Collapsible>
    </template>
  </FormSection>
</template>
