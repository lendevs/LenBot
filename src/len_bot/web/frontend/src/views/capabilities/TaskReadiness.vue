<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import type { RouteLocationRaw } from 'vue-router'
import { ArrowUpRight, Check, Circle, X } from '@lucide/vue'
import { capabilitiesApi } from '../../api/capabilities'
import { keys } from '../../api/query'
import { sceneTitles } from '../../api/scenes'
import { groupsTarget } from '../groups/route'
import Button from '../../ui/Button.vue'
import ErrorNote from '../../ui/ErrorNote.vue'

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
  state: State
  value: string
  to?: RouteLocationRaw
  action?: string
}

const titles = sceneTitles as Record<string, string>
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
    const name = titles[scene.scene] ?? scene.scene
    if (!scene.delegate_roles.length)
      result.push({
        key: `${scene.scene}:roles`,
        label: name,
        state: 'missing',
        value: t('capabilities.worker.ready.noRoles'),
        to: groupsTarget(scene.scene, 'settings'),
        action: t('capabilities.worker.ready.toGroup'),
      })
    else if (scene.missing_tools.length)
      result.push({
        key: `${scene.scene}:tools`,
        label: name,
        state: 'missing',
        value: t('capabilities.worker.ready.tools', { tools: scene.missing_tools.join('、') }),
        to: { name: 'host-persona', query: scene.persona ? { persona: scene.persona } : {} },
        action: t('capabilities.worker.ready.toPersona'),
      })
    else
      result.push({
        key: scene.scene,
        label: name,
        state: 'ok',
        value: t('capabilities.worker.ready.groupReady'),
      })
  }
  result.push({
    key: 'delivery',
    label: t('capabilities.worker.ready.delivery'),
    state: value.delivery === 'onebot' && value.upload_visible_root ? 'ok' : 'neutral',
    value:
      value.delivery === 'simulated'
        ? t('capabilities.worker.ready.simulated')
        : (value.upload_visible_root ?? t('capabilities.worker.ready.sharedFiles')),
    to: { name: 'host-system', query: { tab: 'connection' } },
    action: t('capabilities.worker.ready.toConnection'),
  })
  return result
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
    class="flex min-w-0 flex-col divide-y divide-line rounded-lg border border-line"
  >
    <li
      v-for="item in items"
      :key="item.key"
      class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5"
    >
      <component
        :is="icons[item.state]"
        :size="16"
        class="shrink-0"
        :class="tones[item.state]"
        aria-hidden="true"
      />
      <span class="min-w-0 truncate text-sm font-medium text-ink">{{ item.label }}</span>
      <span class="min-w-0 truncate text-sm text-ink-2" :class="item.state === 'missing' && 'text-error'">
        {{ item.value }}
      </span>
      <Button
        v-if="item.to"
        class="ml-auto"
        size="sm"
        variant="ghost"
        :icon-right="ArrowUpRight"
        :to="item.to"
      >
        {{ item.action }}
      </Button>
    </li>
  </ul>
</template>
