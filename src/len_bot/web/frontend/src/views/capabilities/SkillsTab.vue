<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'
import { ArrowUpRight, BookOpen, FileSearch } from '@lucide/vue'
import { capabilitiesApi, type SkillInfo, type SkillSource } from '../../api/capabilities'
import { personasApi } from '../../api/personas'
import { keys } from '../../api/query'
import { host } from '../../host/store.js'
import { groupLabel } from '../../layouts/shell/scenes'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import EmptyState from '../../ui/EmptyState.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import Select from '../../ui/Select.vue'
import Skeleton from '../../ui/Skeleton.vue'
import SkillDialog from './SkillDialog.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const scenes = computed<string[]>(() => (host.state?.scenes ?? []).map((item: { scene: string }) => item.scene))
const scene = computed({
  get: () => (typeof route.query.scene === 'string' && scenes.value.includes(route.query.scene) ? route.query.scene : (scenes.value[0] ?? '')),
  set: (value: string) => void router.replace({ query: { ...route.query, scene: value } }),
})
const options = computed(() => scenes.value.map((value) => ({ value, label: groupLabel(value) })))
const skills = useQuery({
  queryKey: computed(() => keys.skills.scene(scene.value)),
  queryFn: ({ signal }) => capabilitiesApi.skills(scene.value, signal),
  enabled: computed(() => Boolean(scene.value)),
})
const data = computed(() => skills.data.value)
const roles = useQuery({ queryKey: keys.personas.all(), queryFn: ({ signal }) => personasApi.library(signal) })
const roleKey = computed(() => roles.data.value?.roles.find((role) => role.path === data.value?.role_skills.directory)?.key ?? null)
const order: SkillSource[] = ['scene', 'shared', 'plugin', 'builtin']
const sections = computed(() =>
  order
    .map((source) => ({ source, items: (data.value?.catalog ?? []).filter((skill) => skill.source === source) }))
    .filter((section) => section.items.length),
)
const running = computed(() => new Set((data.value?.running ?? []).map((skill) => `${skill.source}:${skill.name}`)))
const allowance = computed(() => {
  const saved = data.value?.role_skills.saved
  if (saved === undefined) return ''
  return saved === 'all' ? t('capabilities.skills.allowAll') : t('capabilities.skills.allowSome', { n: saved.length }, saved.length)
})

const inspected = ref<SkillInfo | null>(null)
const inspecting = computed({
  get: () => inspected.value !== null,
  set: (value: boolean) => {
    if (!value) inspected.value = null
  },
})
watch(scene, () => (inspected.value = null))
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
    <div class="flex flex-wrap items-end gap-3">
      <Field :label="t('capabilities.skills.group')" class="w-full sm:w-64">
        <Select v-model="scene" :options="options" :placeholder="t('capabilities.skills.noGroups')" :disabled="!options.length" />
      </Field>
      <p v-if="data" class="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 pb-2 text-sm text-muted">
        <span>{{ t('capabilities.skills.role', { name: data.role_skills.persona.name }) }} · {{ allowance }}</span>
        <Badge v-if="data.role_skills.restart_required" tone="warning">{{ t('capabilities.restartPending') }}</Badge>
      </p>
      <Button
        v-if="roleKey"
        size="sm"
        variant="ghost"
        :icon-right="ArrowUpRight"
        :to="{ name: 'host-persona', query: { persona: roleKey, tab: 'abilities' } }"
      >
        {{ t('capabilities.skills.editRole') }}
      </Button>
    </div>

    <EmptyState v-if="!options.length" :icon="BookOpen" :title="t('capabilities.skills.noGroups')" compact />
    <Skeleton v-else-if="skills.isPending.value" :lines="6" />
    <ErrorNote v-else-if="skills.isError.value" :title="t('capabilities.skills.readFailed')" :error="skills.error.value" :retry="skills.refetch" />
    <template v-else-if="data">
      <p v-if="data.directory" class="font-mono text-xs text-subtle">{{ data.directory }}</p>
      <EmptyState v-if="!sections.length" :icon="BookOpen" :title="data.directory ? t('capabilities.skills.empty') : t('capabilities.skills.needsWorker')" compact>
        <Button v-if="!data.directory" size="sm" :to="{ query: { tab: 'tasks' } }">{{ t('capabilities.skills.setUpWorker') }}</Button>
      </EmptyState>
      <section v-for="section in sections" :key="section.source" class="flex flex-col gap-2">
        <h3 class="text-sm font-semibold text-ink-2">
          {{ t(`capabilities.skills.sources.${section.source}`) }} <span class="font-normal text-muted tabular">{{ section.items.length }}</span>
        </h3>
        <ul class="flex list-none flex-col divide-y divide-line rounded-xl border border-line bg-surface px-4">
          <li v-for="skill in section.items" :key="skill.name" class="flex items-center gap-3 py-2.5">
            <div class="min-w-0 flex-1">
              <p class="flex flex-wrap items-center gap-2">
                <code class="font-mono text-sm text-ink">{{ skill.name }}</code>
                <Badge v-if="skill.selected" tone="success">{{ t('capabilities.skills.allowed') }}</Badge>
                <Badge v-if="running.has(`${skill.source}:${skill.name}`)" tone="info">{{ t('capabilities.skills.loaded') }}</Badge>
                <Badge v-if="!skill.model_invocation" tone="warning">{{ t('capabilities.skills.manualOnly') }}</Badge>
              </p>
              <p v-if="skill.description" class="line-clamp-2 text-xs text-muted">{{ skill.description }}</p>
            </div>
            <Button size="sm" variant="ghost" :icon="FileSearch" @click="inspected = skill">{{ t('capabilities.skills.files') }}</Button>
          </li>
        </ul>
      </section>
    </template>
    <SkillDialog
      v-if="inspected"
      :key="`${inspected.source}:${inspected.name}`"
      v-model:open="inspecting"
      :place="{ scene, source: inspected.source, name: inspected.name }"
      @changed="skills.refetch()"
    />
  </div>
</template>
