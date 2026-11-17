<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery } from '@tanstack/vue-query'
import { useRouter } from 'vue-router'
import type { RouteLocationRaw } from 'vue-router'
import { ArrowUpRight, Check, Circle, X } from '@lucide/vue'
import { capabilitiesApi } from '../../api/capabilities'
import { tasksApi } from '../../api/tasks'
import { keys } from '../../api/query'
import { groupLabel } from '../../layouts/shell/scenes'
import { groupsTarget } from '../groups/route'
import Button from '../../ui/Button.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'
import { sceneSecondaryId } from './status'

const props = defineProps<{
  /** Whether the worker model role is bound; tasks use the chat model otherwise. */
  hasModel: boolean
}>()
const { t } = useI18n()
const readiness = useQuery({
  queryKey: keys.host.workerReadiness(),
  queryFn: ({ signal }) => capabilitiesApi.workerReadiness(signal),
})

type State = 'ok' | 'missing' | 'neutral'
interface Item {
  key: string
  label: string
  meta?: string
  state: State
  value: string
  to?: RouteLocationRaw
  action?: string
  /** A ready group where the sample task can run. */
  sample?: string
}

const items = computed<Item[]>(() => {
  const value = readiness.data.value
  if (!value) return []
  const result: Item[] = [
    {
      key: 'sandbox',
      label: t('capabilities.worker.ready.sandbox'),
      state: value.worker ? 'ok' : 'missing',
      value: !value.worker
        ? t('capabilities.worker.ready.notSaved')
        : value.running
          ? t(`capabilities.worker.sandboxes.${value.sandbox ?? 'docker'}`)
          : t('capabilities.worker.ready.restart'),
    },
    {
      key: 'model',
      label: t('capabilities.worker.model'),
      state: props.hasModel ? 'ok' : 'neutral',
      value: props.hasModel ? t('capabilities.worker.ready.ownModel') : t('capabilities.worker.followsChat'),
      to: { name: 'host-models', query: { tab: 'roles' } },
      action: t('capabilities.worker.toModels'),
    },
  ]
  const enabled = value.scenes.filter((scene) => scene.enabled)
  if (!enabled.length)
    result.push({
      key: 'groups',
      label: t('capabilities.worker.ready.groups'),
      state: 'missing',
      value: t('capabilities.worker.ready.noGroup'),
      to: groupsTarget(value.scenes[0]?.scene, 'settings'),
      action: t('capabilities.worker.ready.toGroup'),
    })
  for (const scene of enabled) {
    const name = groupLabel(scene.scene)
    const meta = sceneSecondaryId(scene.scene) || undefined
    if (!scene.delegate_roles.length)
      result.push({
        key: `${scene.scene}:roles`,
        label: name,
        meta,
        state: 'missing',
        value: t('capabilities.worker.ready.noRoles'),
        to: groupsTarget(scene.scene, 'settings'),
        action: t('capabilities.worker.ready.toGroup'),
      })
    else if (scene.missing_tools.length)
      result.push({
        key: `${scene.scene}:tools`,
        label: name,
        meta,
        state: 'missing',
        value: t('capabilities.worker.ready.tools', {
          tools: scene.missing_tools.join(t('personas.separator')),
        }),
        to: { name: 'host-persona', query: scene.persona ? { persona: scene.persona } : {} },
        action: t('capabilities.worker.ready.toPersona'),
      })
    else
      result.push({
        key: scene.scene,
        label: name,
        meta,
        state: 'ok',
        value: t('capabilities.worker.ready.groupReady'),
        sample: value.running ? scene.scene : undefined,
      })
  }
  const live = value.delivery === 'live'
  result.push({
    key: 'delivery',
    label: t('capabilities.worker.ready.delivery'),
    state: live ? 'ok' : 'neutral',
    value: t(`capabilities.worker.ready.${live ? 'onebot' : 'simulated'}`),
    ...(live
      ? {}
      : {
          to: { name: 'host-system', query: { tab: 'connection' } },
          action: t('capabilities.worker.ready.toConnection'),
        }),
  })
  return result
})
const router = useRouter()
const sample = useMutation({
  mutationFn: (scene: string) =>
    tasksApi.delegate(scene, {
      goal: t('capabilities.worker.ready.sampleGoal'),
      deliverable: 'hello.txt',
      context: t('capabilities.worker.ready.sampleContext'),
      materials: [],
    }),
  onSuccess: (task, scene) => void router.push(groupsTarget(scene, 'tasks', { id: task.id })),
  onError: (error) => toast.error(describeError(error, t('ui.error.network')).message),
})
const icons = { ok: Check, missing: X, neutral: Circle }
const tones = { ok: 'text-success', missing: 'text-error', neutral: 'text-subtle' }
</script>

<template>
  <ErrorNote
    v-if="readiness.isError.value"
    :title="t('capabilities.worker.ready.failed')"
    :error="readiness.error.value"
    :retry="readiness.refetch"
  />
  <ul
    v-else-if="items.length"
    class="flex min-w-0 list-none flex-col divide-y divide-line border-y border-line"
  >
    <li
      v-for="item in items"
      :key="item.key"
      class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5"
    >
      <component
        :is="icons[item.state]"
        :size="16"
        class="shrink-0"
        :class="tones[item.state]"
        aria-hidden="true"
      />
      <span class="inline-flex min-w-0 items-baseline gap-1.5">
        <span class="truncate text-sm font-medium text-ink">{{ item.label }}</span>
        <span v-if="item.meta" class="shrink-0 font-mono text-xs text-muted tabular">{{ item.meta }}</span>
      </span>
      <span
        class="min-w-0 flex-1 text-sm break-words"
        :class="item.state === 'missing' ? 'text-error' : 'text-muted'"
      >
        {{ item.value }}
      </span>
      <div v-if="item.to || item.sample" class="ml-auto flex shrink-0 items-center gap-2">
        <Button v-if="item.to" size="sm" variant="ghost" :icon-right="ArrowUpRight" :to="item.to">
          {{ item.action }}
        </Button>
        <Button
          v-if="item.sample"
          size="sm"
          variant="secondary"
          :loading="sample.isPending.value && sample.variables.value === item.sample"
          @click="sample.mutate(item.sample)"
        >
          {{ t('capabilities.worker.ready.sample') }}
        </Button>
      </div>
    </li>
  </ul>
</template>
