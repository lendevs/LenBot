<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { ArrowUpRight, MessagesSquare, Repeat, Search } from '@lucide/vue'
import type { HostScene } from '../../../api/host'
import type { PersonaRole } from '../../../api/personas'
import { keys } from '../../../api/query'
import { settingsApi } from '../../../api/settings'
import { host, readHostState } from '../../../api/hostStore'
import { groupLabel, groupSecondaryId } from '../../../layouts/shell/scenes'
import Avatar from '../../../ui/Avatar.vue'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import Checkbox from '../../../ui/Checkbox.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import IconButton from '../../../ui/IconButton.vue'
import Input from '../../../ui/Input.vue'
import { confirm } from '../../../ui/confirm'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import { groupsTarget } from '../../groups/route'

const props = defineProps<{ role: PersonaRole; blocked: string | null }>()

const { t } = useI18n()
const client = useQueryClient()
const name = computed(() => props.role.name || props.role.key)
const scenes = computed(() => (host.state?.scenes ?? []) as HostScene[])

interface SceneRow {
  scene: string
  current: string
  using: boolean
  waiting: boolean
}

const rows = computed<SceneRow[]>(() => {
  const rank = (row: SceneRow) => (row.using ? 0 : row.waiting ? 1 : 2)
  return scenes.value
    .map((item) => ({
      scene: item.scene,
      current: item.persona.name,
      using: item.persona_path === props.role.path && props.role.running_scenes.includes(item.scene),
      // Saved for this role while the group still finishes a reply with the previous one.
      waiting: props.role.scenes.includes(item.scene) && !props.role.running_scenes.includes(item.scene),
    }))
    .sort((a, b) => rank(a) - rank(b))
})

const search = ref('')
const shownRows = computed(() => {
  const words = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return rows.value
  return rows.value.filter((row) => {
    const text = [groupLabel(row.scene), groupSecondaryId(row.scene), row.scene, row.current]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return words.every((word) => text.includes(word))
  })
})

const chosen = ref<string[]>([])
watch(
  () => props.role.scenes.join(),
  () => (chosen.value = chosen.value.filter((scene) => !props.role.scenes.includes(scene))),
)
const choosable = computed(() =>
  rows.value.filter((row) => !row.using && !row.waiting).map((row) => row.scene),
)
const visibleChoosable = computed(() =>
  shownRows.value.filter((row) => !row.using && !row.waiting).map((row) => row.scene),
)
const chosenVisibleCount = computed(
  () => visibleChoosable.value.filter((scene) => chosen.value.includes(scene)).length,
)

function toggle(scene: string, on: boolean) {
  chosen.value = on ? [...new Set([...chosen.value, scene])] : chosen.value.filter((item) => item !== scene)
}
function toggleVisibleAll(on: boolean) {
  if (on) {
    chosen.value = [...new Set([...chosen.value, ...visibleChoosable.value])]
  } else {
    const visible = new Set(visibleChoosable.value)
    chosen.value = chosen.value.filter((item) => !visible.has(item))
  }
}
function canPick(row: SceneRow) {
  return !row.using && !row.waiting && !props.blocked && !use.isPending.value
}
function onRowClick(row: SceneRow, event: MouseEvent) {
  if (!canPick(row)) return
  const target = event.target as HTMLElement | null
  if (target?.closest('a, button, input, [role="checkbox"]')) return
  toggle(row.scene, !chosen.value.includes(row.scene))
}

const use = useMutation({
  mutationFn: (targets: string[]) => settingsApi.useRole(props.role.key, targets),
  onSuccess: ({ results }) => {
    const failed = results.filter((item) => item.status === 'failed')
    const pending = results.filter((item) => item.status === 'pending')
    if (failed.length) {
      toast.error(
        t('personas.detail.scenes.failed', {
          names: failed.map((item) => groupLabel(item.scene)).join(t('personas.separator')),
        }),
        {
          detail: failed.map((item) => `${groupLabel(item.scene)}: ${item.error ?? ''}`).join('\n'),
        },
      )
    }
    if (results.length > failed.length) {
      toast.success(
        pending.length
          ? t('personas.detail.scenes.pending', {
              names: pending.map((item) => groupLabel(item.scene)).join(t('personas.separator')),
              name: name.value,
            })
          : t('personas.detail.scenes.done', { name: name.value }),
      )
    }
    if (results.some((item) => item.handover === 'failed'))
      toast.error(t('groups.settings.role.handoverFailed'))
    chosen.value = []
  },
  onError: (error) =>
    toast.error(t('personas.detail.scenes.failedAll'), {
      detail: describeError(error, t('ui.error.network')).message,
    }),
  onSettled: () => {
    void client.invalidateQueries({ queryKey: keys.personas.all() })
    void client.invalidateQueries({ queryKey: keys.host.settings() })
    void readHostState()
  },
})
async function apply() {
  const sure = await confirm({
    title: t(
      'personas.detail.scenes.confirm',
      { n: chosen.value.length, name: name.value },
      chosen.value.length,
    ),
    message: chosen.value.map(groupLabel).join(t('personas.separator')),
    confirmLabel: t('personas.detail.scenes.apply'),
    tone: 'primary',
  })
  if (sure) use.mutate([...chosen.value])
}
</script>

<template>
  <EmptyState v-if="!rows.length" :icon="MessagesSquare" :title="t('groups.empty')" />
  <div v-else class="flex max-w-3xl flex-col gap-4">
    <div v-if="rows.length > 4 || choosable.length" class="flex flex-wrap items-center gap-3">
      <div v-if="rows.length > 4" class="w-full sm:w-64">
        <Input
          v-model="search"
          type="search"
          size="sm"
          :icon="Search"
          clearable
          :placeholder="t('groups.search')"
          :aria-label="t('groups.search')"
        />
      </div>
      <Checkbox
        v-if="visibleChoosable.length"
        :model-value="
          chosenVisibleCount === 0
            ? false
            : chosenVisibleCount === visibleChoosable.length
              ? true
              : 'indeterminate'
        "
        :disabled="!visibleChoosable.length || Boolean(blocked)"
        @update:model-value="(on) => toggleVisibleAll(on === true)"
      >
        <span class="text-sm text-ink-2">{{ t('personas.detail.scenes.selectAll') }}</span>
      </Checkbox>
      <div v-if="choosable.length" class="ml-auto tabular">
        <Button
          variant="primary"
          size="sm"
          :icon="Repeat"
          :loading="use.isPending.value"
          :disabled="!chosen.length || Boolean(blocked)"
          @click="apply"
        >
          {{
            chosen.length
              ? t('personas.detail.scenes.applyCount', { n: chosen.length }, chosen.length)
              : t('personas.detail.scenes.apply')
          }}
        </Button>
      </div>
    </div>
    <p v-if="blocked" class="text-sm text-warning">{{ blocked }}</p>
    <p v-if="!shownRows.length" class="py-6 text-center text-sm text-muted">
      {{ t('common.noResults') }}
    </p>
    <ul v-else class="flex list-none flex-col divide-y divide-line border-y border-line">
      <li
        v-for="row in shownRows"
        :key="row.scene"
        class="flex min-h-14 items-center gap-3 px-2 py-2.5 transition-colors"
        :class="canPick(row) && 'cursor-pointer hover:bg-hover/60'"
        @click="onRowClick(row, $event)"
      >
        <Checkbox
          v-if="!row.using && !row.waiting"
          :model-value="chosen.includes(row.scene)"
          :disabled="Boolean(blocked) || use.isPending.value"
          :aria-label="groupLabel(row.scene)"
          @update:model-value="(on) => toggle(row.scene, on === true)"
        />
        <span v-else-if="choosable.length" class="size-4.5 shrink-0" aria-hidden="true" />
        <Avatar :name="groupLabel(row.scene)" shape="square" :size="32" />
        <span class="min-w-0 flex-1">
          <span
            class="block truncate text-sm font-medium text-ink"
            :class="!groupSecondaryId(row.scene) && 'tabular'"
          >
            {{ groupLabel(row.scene) }}
          </span>
          <span
            v-if="groupSecondaryId(row.scene) || (!row.using && row.current)"
            class="flex min-w-0 items-center gap-1.5 text-xs text-muted"
          >
            <span v-if="groupSecondaryId(row.scene)" class="shrink-0 font-mono text-subtle tabular">
              {{ groupSecondaryId(row.scene) }}
            </span>
            <template v-if="!row.using && row.current">
              <span v-if="groupSecondaryId(row.scene)" class="text-subtle" aria-hidden="true">·</span>
              <span class="truncate">{{ row.current }}</span>
            </template>
          </span>
        </span>
        <Badge v-if="row.using" tone="success" dot>{{ t('personas.detail.scenes.using') }}</Badge>
        <Badge v-else-if="row.waiting" tone="warning" dot pulse>
          {{ t('personas.detail.scenes.waiting') }}
        </Badge>
        <IconButton
          :icon="ArrowUpRight"
          :label="t('personas.detail.scenes.open')"
          size="sm"
          :to="groupsTarget(row.scene, 'settings')"
        />
      </li>
    </ul>
  </div>
</template>
