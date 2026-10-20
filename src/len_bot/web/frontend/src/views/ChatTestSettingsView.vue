<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { Plus, Trash2 } from '@lucide/vue'
import { keys } from '../api/query'
import type { PersonaExample } from '../api/personas'
import { chatTestApi, type ScenePersonaValues } from '../api/trials'
import { useUnsavedChanges } from '../composables/useUnsavedChanges'
import Badge from '../ui/Badge.vue'
import Button from '../ui/Button.vue'
import ErrorNote from '../ui/ErrorNote.vue'
import Field from '../ui/Field.vue'
import FormSection from '../ui/FormSection.vue'
import IconButton from '../ui/IconButton.vue'
import Input from '../ui/Input.vue'
import SaveBar from '../ui/SaveBar.vue'
import Skeleton from '../ui/Skeleton.vue'
import TagInput from '../ui/TagInput.vue'
import Textarea from '../ui/Textarea.vue'
import { describeError } from '../ui/errors'
import { toast } from '../ui/toast'

interface Draft {
  aliases: string[]
  relationships: { account: string; text: string }[]
  addendum: string
}

const ACCOUNT = /^[a-z][a-z0-9_-]*:[^:\s/\\]+$/
const { t } = useI18n()
const client = useQueryClient()
const settings = useQuery({
  queryKey: keys.chatTest.settings(),
  queryFn: ({ signal }) => chatTestApi.settings(signal),
})
const stored = useQuery({
  queryKey: keys.chatTest.scenePersona(),
  queryFn: ({ signal }) => chatTestApi.scenePersona(signal),
})

const draftOf = (saved: ScenePersonaValues): Draft => ({
  aliases: [...saved.persona_aliases],
  relationships: Object.entries(saved.relationships).map(([account, text]) => ({ account, text })),
  addendum: saved.behavior_addendum ?? '',
})
const body = (draft: Draft): ScenePersonaValues => ({
  persona_aliases: draft.aliases.map((alias) => alias.trim()),
  relationships: Object.fromEntries(draft.relationships.map((row) => [row.account.trim(), row.text.trim()])),
  behavior_addendum: draft.addendum.trim() || null,
})
const draft = ref<Draft | null>(null)
watch(
  () => stored.data.value?.saved,
  (saved) => {
    if (saved) draft.value = draftOf(saved)
  },
  { immediate: true },
)
// Compared row by row: a repeated account would collapse in the saved object and hide the edit.
const dirty = computed(() => {
  const saved = stored.data.value?.saved
  return Boolean(saved && draft.value) && JSON.stringify(draft.value) !== JSON.stringify(draftOf(saved!))
})
useUnsavedChanges(dirty)

const errors = computed(() => {
  const found: Record<string, string> = {}
  if (!draft.value) return found
  const seen = new Set<string>()
  draft.value.relationships.forEach((row, index) => {
    const account = row.account.trim()
    if (!ACCOUNT.test(account)) found[`${index}.account`] = t('groups.settings.errors.account')
    else if (seen.has(account)) found[`${index}.account`] = t('groups.settings.errors.repeated')
    seen.add(account)
    if (!row.text.trim()) found[`${index}.text`] = t('common.required')
  })
  return found
})

const save = useMutation({
  mutationFn: () => chatTestApi.saveScenePersona(body(draft.value!)),
  onSuccess: (result) => {
    client.setQueryData(keys.chatTest.scenePersona(), result)
    draft.value = draftOf(result.saved)
    toast.success(result.restart_required ? t('chatTest.settings.savedRestart') : t('common.saved'))
  },
})
const saveError = computed(() =>
  save.isError.value ? describeError(save.error.value, t('ui.error.network')).message : null,
)

const list = (items: string[]) =>
  items.length ? items.join(t('chatTest.settings.separator')) : t('chatTest.settings.none')
/** Tool and skill names show as code; the words for all and none do not. */
const names = (value: 'all' | string[]) => Array.isArray(value) && value.length > 0
const access = (value: 'all' | string[]) => (value === 'all' ? t('chatTest.settings.all') : list(value))
const facts = computed(() => {
  const data = settings.data.value
  if (!data) return []
  return [
    { label: t('chatTest.settings.scene'), value: data.scene, mono: true },
    { label: t('chatTest.settings.bot'), value: data.bot_id, mono: true },
    { label: t('chatTest.settings.timezone'), value: data.timezone, mono: true },
    {
      label: t('chatTest.settings.delivery'),
      value: data.delivery === 'simulated' ? t('chatTest.settings.simulated') : data.delivery,
      mono: data.delivery !== 'simulated',
    },
  ]
})
const exampleKey = (example: PersonaExample, index: number) => `${index}:${example.line}`
</script>

<template>
  <div class="flex min-w-0 max-w-4xl flex-col gap-8">
    <Skeleton v-if="stored.isPending.value" :lines="5" />
    <ErrorNote
      v-else-if="stored.isError.value"
      :title="t('chatTest.settings.readFailed')"
      :error="stored.error.value"
      :retry="stored.refetch"
    />
    <form v-else-if="draft" class="flex flex-col gap-5" @submit.prevent="save.mutate()">
      <FormSection :title="t('chatTest.settings.additions')" :columns="1">
        <template v-if="stored.data.value?.restart_required" #actions>
          <Badge tone="warning">{{ t('chatTest.settings.restart') }}</Badge>
        </template>
        <Field :label="t('groups.settings.persona.aliases')">
          <TagInput v-model="draft.aliases" />
        </Field>
        <Field :label="t('groups.settings.persona.relationships')">
          <div class="flex flex-col gap-2">
            <div
              v-for="(row, index) in draft.relationships"
              :key="index"
              class="grid items-start gap-2 sm:grid-cols-[180px_minmax(0,1fr)_auto]"
            >
              <Field :error="errors[`${index}.account`]">
                <Input
                  v-model="row.account"
                  placeholder="onebot:10001"
                  mono
                  :aria-label="t('groups.settings.persona.account')"
                />
              </Field>
              <Field :error="errors[`${index}.text`]">
                <Input v-model="row.text" :aria-label="t('groups.settings.persona.relationship')" />
              </Field>
              <IconButton
                :icon="Trash2"
                :label="t('common.delete')"
                variant="ghost"
                @click="draft.relationships.splice(index, 1)"
              />
            </div>
            <div>
              <Button
                size="sm"
                variant="ghost"
                :icon="Plus"
                @click="draft.relationships.push({ account: '', text: '' })"
              >
                {{ t('groups.settings.persona.add') }}
              </Button>
            </div>
          </div>
        </Field>
        <Field :label="t('groups.settings.persona.addendum')">
          <Textarea v-model="draft.addendum" :rows="3" />
        </Field>
      </FormSection>
      <SaveBar
        :dirty="dirty"
        :saving="save.isPending.value"
        :error="saveError"
        :invalid="Object.keys(errors).length > 0"
        @save="save.mutate()"
        @discard="draft = draftOf(stored.data.value!.saved)"
      />
    </form>

    <Skeleton v-if="settings.isPending.value" :lines="8" />
    <ErrorNote
      v-else-if="settings.isError.value"
      :title="t('chatTest.settings.readFailed')"
      :error="settings.error.value"
      :retry="settings.refetch"
    />
    <template v-else-if="settings.data.value">
      <FormSection :title="t('chatTest.settings.running')">
        <dl class="contents">
          <div v-for="fact in facts" :key="fact.label" class="flex min-w-0 flex-col gap-1">
            <dt class="text-xs text-muted">{{ fact.label }}</dt>
            <dd class="text-sm" :class="fact.mono && 'truncate font-mono'">{{ fact.value }}</dd>
          </div>
        </dl>
      </FormSection>

      <FormSection
        :title="t('chatTest.settings.persona', { name: settings.data.value.persona.name })"
        :columns="1"
      >
        <dl class="flex flex-col gap-4 text-sm">
          <div
            v-for="field in ['brief', 'behavior', 'voice', 'boundaries'] as const"
            :key="field"
            class="flex flex-col gap-1"
          >
            <dt class="text-xs text-muted">{{ t(`chatTest.settings.fields.${field}`) }}</dt>
            <dd class="whitespace-pre-wrap text-ink-2">
              {{ settings.data.value.persona[field] || t('chatTest.settings.none') }}
            </dd>
          </div>
          <div class="grid gap-4 sm:grid-cols-2">
            <div class="flex flex-col gap-1">
              <dt class="text-xs text-muted">{{ t('chatTest.settings.fields.selfReference') }}</dt>
              <dd class="text-ink-2">{{ list(settings.data.value.persona.self_reference) }}</dd>
            </div>
            <div class="flex flex-col gap-1">
              <dt class="text-xs text-muted">{{ t('chatTest.settings.fields.aliases') }}</dt>
              <dd class="text-ink-2">{{ list(settings.data.value.persona.aliases) }}</dd>
            </div>
          </div>
          <div class="flex flex-col gap-1">
            <dt class="text-xs text-muted">{{ t('chatTest.settings.fields.styles') }}</dt>
            <dd v-if="settings.data.value.persona.styles.length" class="flex flex-wrap gap-1.5">
              <Badge v-for="style in settings.data.value.persona.styles" :key="style.name">
                {{ style.name }} · {{ Math.round(style.weight * 100) }}%
              </Badge>
            </dd>
            <dd v-else class="text-ink-2">{{ t('chatTest.settings.baseVoice') }}</dd>
          </div>
        </dl>
      </FormSection>

      <FormSection
        :title="
          t(
            'chatTest.settings.examples',
            { n: settings.data.value.selected_examples.length },
            settings.data.value.selected_examples.length,
          )
        "
        :columns="1"
      >
        <p class="text-sm text-muted">
          {{
            settings.data.value.persona.example_tags.length
              ? t('chatTest.settings.exampleTags', { tags: list(settings.data.value.persona.example_tags) })
              : t('chatTest.settings.noExampleTags')
          }}
        </p>
        <ol v-if="settings.data.value.selected_examples.length" class="flex list-none flex-col gap-2">
          <li
            v-for="(example, index) in settings.data.value.selected_examples"
            :key="exampleKey(example, index)"
            class="flex flex-col gap-1 rounded-lg border border-line px-3 py-2 text-sm"
          >
            <p class="whitespace-pre-wrap text-muted">{{ example.context }}</p>
            <p class="whitespace-pre-wrap text-ink">{{ example.line }}</p>
            <p v-if="example.tags.length" class="flex flex-wrap gap-1">
              <Badge v-for="tag in example.tags" :key="tag">{{ tag }}</Badge>
            </p>
          </li>
        </ol>
      </FormSection>

      <FormSection :title="t('chatTest.settings.knowledge')" :columns="1">
        <ul
          v-if="settings.data.value.knowledge.length"
          class="flex list-none flex-col divide-y divide-line rounded-lg border border-line"
        >
          <li
            v-for="file in settings.data.value.knowledge"
            :key="file.filename"
            class="flex flex-wrap items-center gap-2 px-3 py-2 text-sm"
          >
            <span class="min-w-0 flex-1 truncate font-mono">{{ file.filename }}</span>
            <Badge v-for="tag in file.tags" :key="tag">{{ tag }}</Badge>
            <span class="text-xs text-muted tabular">
              {{ t('chatTest.settings.characters', { n: file.characters }) }}
            </span>
          </li>
        </ul>
        <p v-else class="text-sm text-muted">{{ t('chatTest.settings.noKnowledge') }}</p>
      </FormSection>

      <FormSection :title="t('chatTest.settings.tools')">
        <div class="flex flex-col gap-1 text-sm">
          <span class="text-xs text-muted">{{ t('chatTest.settings.coreTools') }}</span>
          <span class="text-ink-2" :class="names(settings.data.value.tools.core) && 'font-mono'">
            {{ list(settings.data.value.tools.core) }}
          </span>
        </div>
        <div class="flex flex-col gap-1 text-sm">
          <span class="text-xs text-muted">{{ t('chatTest.settings.deferredTools') }}</span>
          <span class="text-ink-2" :class="names(settings.data.value.tools.deferred) && 'font-mono'">
            {{ list(settings.data.value.tools.deferred) }}
          </span>
        </div>
        <div class="flex flex-col gap-1 text-sm">
          <span class="text-xs text-muted">{{ t('chatTest.settings.roleTools') }}</span>
          <span class="text-ink-2" :class="names(settings.data.value.persona.tools) && 'font-mono'">
            {{ access(settings.data.value.persona.tools) }}
          </span>
        </div>
        <div class="flex flex-col gap-1 text-sm">
          <span class="text-xs text-muted">{{ t('chatTest.settings.roleSkills') }}</span>
          <span class="text-ink-2" :class="names(settings.data.value.persona.skills) && 'font-mono'">
            {{ access(settings.data.value.persona.skills) }}
          </span>
        </div>
      </FormSection>
    </template>
  </div>
</template>
