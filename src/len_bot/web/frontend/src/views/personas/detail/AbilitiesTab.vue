<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { FileSearch, Puzzle, Search, TriangleAlert } from '@lucide/vue'
import { keys } from '../../../api/query'
import {
  personasApi,
  type Abilities,
  type Allowance,
  type Applied,
  type SkillInfo,
  type ToolInfo,
} from '../../../api/personas'
import { developerDetails } from '../../../composables/useDeveloperMode'
import { readPendingRestart } from '../../../api/hostStore'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import Checkbox from '../../../ui/Checkbox.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import SkillDialog from '../../capabilities/SkillDialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import Input from '../../../ui/Input.vue'
import SaveBar from '../../../ui/SaveBar.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Switch from '../../../ui/Switch.vue'
import { describeError } from '../../../ui/errors'
import RawRecord from '../../groups/tasks/RawRecord.vue'
import { useLiveLabels } from '../../groups/live/labels'
import { useRoleWrites } from './writes'

const props = defineProps<{ persona: string }>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t, te } = useI18n()
const labels = useLiveLabels()
const client = useQueryClient()
const writes = useRoleWrites(computed(() => props.persona))
const abilitiesKey = computed(() => keys.personas.part(props.persona, 'abilities'))
const abilities = useQuery({
  queryKey: abilitiesKey,
  queryFn: ({ signal }) => personasApi.abilities(props.persona, signal),
})

const copy = (value: Allowance): Allowance => (value === 'all' ? 'all' : [...value])
const sorted = (value: Allowance) => (value === 'all' ? value : [...value].sort().join())
const tools = ref<Allowance>([])
const skills = ref<Allowance>([])
const baseTools = ref<Allowance | null>(null)
const baseSkills = ref<Allowance | null>(null)

function adopt() {
  const data = abilities.data.value
  if (!data) return
  tools.value = copy(data.tools.saved)
  skills.value = copy(data.skills.saved)
  baseTools.value = copy(data.tools.saved)
  baseSkills.value = copy(data.skills.saved)
  save.reset()
}

// Keep unsaved checkboxes across window-refocus refetches; auto-merge untouched parts.
watch(
  () => abilities.data.value,
  (data) => {
    if (!data) return
    if (baseTools.value === null || baseSkills.value === null) {
      tools.value = copy(data.tools.saved)
      skills.value = copy(data.skills.saved)
      baseTools.value = copy(data.tools.saved)
      baseSkills.value = copy(data.skills.saved)
      return
    }
    if (sorted(data.tools.saved) !== sorted(baseTools.value)) {
      if (
        sorted(tools.value) === sorted(baseTools.value) ||
        sorted(tools.value) === sorted(data.tools.saved)
      ) {
        tools.value = copy(data.tools.saved)
        baseTools.value = copy(data.tools.saved)
      }
    }
    if (sorted(data.skills.saved) !== sorted(baseSkills.value)) {
      if (
        sorted(skills.value) === sorted(baseSkills.value) ||
        sorted(skills.value) === sorted(data.skills.saved)
      ) {
        skills.value = copy(data.skills.saved)
        baseSkills.value = copy(data.skills.saved)
      }
    }
  },
  { immediate: true },
)

const toolsChanged = computed(
  () => Boolean(abilities.data.value) && sorted(tools.value) !== sorted(abilities.data.value!.tools.saved),
)
const skillsChanged = computed(
  () => Boolean(abilities.data.value) && sorted(skills.value) !== sorted(abilities.data.value!.skills.saved),
)
const dirty = computed(() => toolsChanged.value || skillsChanged.value)
watch(dirty, (value) => emit('dirty', value), { immediate: true })

const remoteUpdated = computed(() => {
  const data = abilities.data.value
  if (!data || baseTools.value === null || baseSkills.value === null) return false
  const toolsConflict =
    sorted(tools.value) !== sorted(baseTools.value) &&
    sorted(data.tools.saved) !== sorted(baseTools.value) &&
    sorted(tools.value) !== sorted(data.tools.saved)
  const skillsConflict =
    sorted(skills.value) !== sorted(baseSkills.value) &&
    sorted(data.skills.saved) !== sorted(baseSkills.value) &&
    sorted(skills.value) !== sorted(data.skills.saved)
  return toolsConflict || skillsConflict
})

const catalog = computed(() => abilities.data.value?.tools.catalog ?? [])
const toolSearch = ref('')
const note = (tool: ToolInfo) =>
  te(`personas.detail.abilities.notes.${tool.name}`)
    ? t(`personas.detail.abilities.notes.${tool.name}`)
    : tool.summary
const filteredCatalog = computed(() => {
  const words = toolSearch.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return catalog.value
  return catalog.value.filter((tool) => {
    const text = [tool.name, labels.tool(tool.name), note(tool), tool.source ?? ''].join(' ').toLowerCase()
    return words.every((word) => text.includes(word))
  })
})
const builtIn = computed(() => filteredCatalog.value.filter((tool) => !tool.source))
const extra = computed(() => filteredCatalog.value.filter((tool) => tool.source))
const toolGroups = computed(() =>
  [
    { key: 'built-in', title: t('personas.detail.abilities.builtInTools'), items: builtIn.value },
    { key: 'extra', title: t('personas.detail.abilities.extraTools'), items: extra.value },
  ].filter((group) => group.items.length > 0),
)

/** Tools that only work together: picking the first adds the rest. */
const companions: Record<string, string[]> = {
  schedule: ['schedule_list', 'schedule_cancel'],
  delegate: ['task'],
}
function toggleTool(name: string, on: boolean) {
  if (tools.value === 'all') return
  const before = tools.value
  let next = on ? [...before, name] : before.filter((item) => item !== name)
  if (on) {
    next = [...next, ...(companions[name] ?? [])]
    const deferred = catalog.value.some((tool) => tool.name === name && tool.deferred)
    if (deferred) next.push('tool_search')
  }
  tools.value = [...new Set(next)]
}
function allTools(on: boolean) {
  // Tools the group cannot assemble are refused on save, so the explicit list starts with the usable ones.
  tools.value = on ? 'all' : catalog.value.filter((tool) => !tool.reasons.length).map((tool) => tool.name)
}
const allowed = (value: Allowance, name: string) => value === 'all' || value.includes(name)

const skillCatalog = computed(() => abilities.data.value?.skills.catalog ?? [])
function toggleSkill(name: string, on: boolean) {
  if (skills.value === 'all') return
  skills.value = on ? [...new Set([...skills.value, name])] : skills.value.filter((item) => item !== name)
}
function allSkills(on: boolean) {
  skills.value = on ? 'all' : skillCatalog.value.map((skill) => skill.name)
}
const inspected = ref<SkillInfo | null>(null)
const inspecting = computed({
  get: () => inspected.value !== null,
  set: (value: boolean) => {
    if (!value) inspected.value = null
  },
})
function skillChanged() {
  inspected.value = null
  void abilities.refetch()
}

const save = useMutation({
  mutationFn: async () => {
    const directory = abilities.data.value!.directory
    const results: Applied[] = []
    if (toolsChanged.value) {
      const saved = await personasApi.saveTools(props.persona, directory, tools.value)
      results.push(saved)
      baseTools.value = copy(saved.saved)
      tools.value = copy(saved.saved)
      client.setQueryData<Abilities>(abilitiesKey.value, (prev) =>
        prev ? { ...prev, tools: { ...prev.tools, saved: copy(saved.saved) } } : prev,
      )
    }
    if (skillsChanged.value) {
      const saved = await personasApi.saveSkills(props.persona, directory, skills.value)
      results.push(saved)
      baseSkills.value = copy(saved.saved)
      skills.value = copy(saved.saved)
      client.setQueryData<Abilities>(abilitiesKey.value, (prev) =>
        prev ? { ...prev, skills: { ...prev.skills, saved: copy(saved.saved) } } : prev,
      )
    }
    const errors = results.map((item) => item.apply_error).filter((item): item is string => Boolean(item))
    return {
      affected_scenes: [...new Set(results.flatMap((item) => item.affected_scenes ?? []))],
      applied: results.every((item) => item.applied !== false),
      apply_error: errors.length ? errors.join('\n') : null,
    } satisfies Applied
  },
  onSuccess: (result) => {
    writes.done(result, ['abilities', 'files'])
    void readPendingRestart()
  },
  // Tools may have been saved before skills failed.
  onError: () => void client.invalidateQueries({ queryKey: abilitiesKey.value }),
})
</script>

<template>
  <Skeleton v-if="abilities.isPending.value" :lines="8" />
  <ErrorNote
    v-else-if="abilities.isError.value"
    :title="t('personas.detail.abilities.readFailed')"
    :error="abilities.error.value"
    :retry="abilities.refetch"
  />
  <form v-else class="flex max-w-3xl flex-col gap-8 pb-6" @submit.prevent="save.mutate()">
    <div
      v-if="remoteUpdated"
      role="status"
      class="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-warning-bg px-3.5 py-2.5 text-sm text-warning"
    >
      <span class="min-w-0 flex-1">{{ t('ui.draft.remoteUpdated') }}</span>
      <Button size="sm" variant="ghost" @click="adopt">
        {{ t('ui.draft.reloadRemote') }}
      </Button>
    </div>

    <FormSection :title="t('personas.detail.abilities.tools')" :columns="1">
      <Field :label="t('personas.detail.abilities.allTools')" inline>
        <Switch :model-value="tools === 'all'" @update:model-value="allTools" />
      </Field>
      <div v-if="catalog.length" class="max-w-xs">
        <Input
          v-model="toolSearch"
          type="search"
          size="sm"
          :icon="Search"
          clearable
          :placeholder="t('personas.detail.abilities.searchTools')"
          :aria-label="t('personas.detail.abilities.searchTools')"
        />
      </div>
      <p v-if="toolSearch.trim() && !toolGroups.length" class="py-4 text-center text-sm text-muted">
        {{ t('common.noResults') }}
      </p>
      <div v-for="group in toolGroups" :key="group.key" class="flex flex-col gap-2">
        <h4 class="flex items-center gap-2 text-xs font-medium text-muted">
          <span>{{ group.title }}</span>
          <span class="tabular">{{ group.items.length }}</span>
        </h4>
        <ul class="flex list-none flex-col divide-y divide-line border-y border-line">
          <li v-for="tool in group.items" :key="tool.name" class="flex flex-col gap-1.5 py-3">
            <Checkbox
              :model-value="allowed(tools, tool.name)"
              :disabled="tools === 'all' || (tool.reasons.length > 0 && !allowed(tools, tool.name))"
              @update:model-value="(on) => toggleTool(tool.name, on === true)"
            >
              <span class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
                <span class="text-sm font-medium text-ink">{{ labels.tool(tool.name) }}</span>
                <code class="font-mono text-xs text-subtle">{{ tool.name }}</code>
                <Badge v-if="tool.source">{{ tool.source }}</Badge>
              </span>
            </Checkbox>
            <p class="line-clamp-2 pl-7 text-sm text-muted">{{ note(tool) }}</p>
            <p v-if="tool.reasons.length" class="flex items-start gap-1.5 pl-7 text-xs text-warning">
              <TriangleAlert :size="13" class="mt-0.5 shrink-0" aria-hidden="true" />
              {{ tool.reasons.join(t('personas.detail.abilities.reasonSeparator')) }}
            </p>
            <div v-if="developerDetails" class="pl-7">
              <RawRecord
                :label="t('personas.detail.abilities.forModel')"
                :code="{
                  description: tool.description,
                  parameters: tool.parameters,
                  instructions: tool.instructions,
                }"
              />
            </div>
          </li>
        </ul>
      </div>
    </FormSection>

    <FormSection :title="t('personas.detail.abilities.skills')" :columns="1">
      <EmptyState
        v-if="!skillCatalog.length"
        :icon="Puzzle"
        :title="t('personas.detail.abilities.noSkills')"
        compact
      />
      <template v-else>
        <Field :label="t('personas.detail.abilities.allSkills')" inline>
          <Switch :model-value="skills === 'all'" @update:model-value="allSkills" />
        </Field>
        <ul class="flex list-none flex-col divide-y divide-line border-y border-line">
          <li
            v-for="skill in skillCatalog"
            :key="`${skill.source}:${skill.name}`"
            class="flex flex-wrap items-start justify-between gap-x-3 gap-y-2 py-3"
          >
            <div class="flex min-w-0 flex-1 flex-col gap-1">
              <Checkbox
                :model-value="allowed(skills, skill.name)"
                :disabled="skills === 'all'"
                @update:model-value="(on) => toggleSkill(skill.name, on === true)"
              >
                <span class="flex min-w-0 flex-wrap items-center gap-2">
                  <span class="text-sm font-medium text-ink">{{ skill.name }}</span>
                  <Badge>{{ t(`personas.detail.abilities.sources.${skill.source}`) }}</Badge>
                </span>
              </Checkbox>
              <p class="line-clamp-2 pl-7 text-sm text-muted">{{ skill.description }}</p>
            </div>
            <Button size="sm" variant="ghost" :icon="FileSearch" @click="inspected = skill">
              {{ t('personas.detail.abilities.files') }}
            </Button>
          </li>
        </ul>
      </template>
    </FormSection>

    <SaveBar
      :dirty="dirty"
      :saving="save.isPending.value"
      :error="save.isError.value ? describeError(save.error.value, t('ui.error.network')).message : null"
      :raw-error="save.isError.value ? describeError(save.error.value, t('ui.error.network')).raw : null"
      @save="save.mutate()"
      @discard="adopt"
    />
    <SkillDialog
      v-if="inspected && abilities.data.value"
      :key="`${inspected.source}:${inspected.name}`"
      v-model:open="inspecting"
      :place="{ scene: abilities.data.value.scene, source: inspected.source, name: inspected.name }"
      @changed="skillChanged"
    />
  </form>
</template>
