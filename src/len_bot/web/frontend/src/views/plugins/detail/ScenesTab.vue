<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQueryClient } from '@tanstack/vue-query'
import { MessagesSquare, Search, Settings2 } from '@lucide/vue'
import { pluginsApi, type PluginsSnapshot } from '../../../api/plugins'
import { keys } from '../../../api/query'
import { readPendingRestart } from '../../../api/hostStore'
import { groupLabel } from '../../../layouts/shell/scenes'
import Avatar from '../../../ui/Avatar.vue'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import IconButton from '../../../ui/IconButton.vue'
import Input from '../../../ui/Input.vue'
import Switch from '../../../ui/Switch.vue'
import { describeError } from '../../../ui/errors'
import { toast } from '../../../ui/toast'
import { groupsTarget } from '../../groups/route'
import { confirmMemorySwitch } from '../../groups/settings/memory'
import { usePluginsState } from '../state'
import { chatPlatformsOf, enabledIn, manifestOf, sceneSecondaryId, scenesUsing } from '../view'

const props = defineProps<{ name: string; snapshot: PluginsSnapshot }>()

const { t } = useI18n()
const client = useQueryClient()
const state = usePluginsState()
const search = ref('')
const used = computed(() => scenesUsing(props.snapshot, props.name))
const platforms = computed(() => chatPlatformsOf(props.snapshot, props.name))
// Groups on platforms the plugin does not declare are left out, except ones already using it.
const scenes = computed(() =>
  Object.keys(props.snapshot.scenes).filter(
    (scene) =>
      !platforms.value || platforms.value.includes(scene.split(':')[0]) || used.value.includes(scene),
  ),
)
const filteredScenes = computed(() => {
  const words = search.value.trim().toLowerCase()
  if (!words) return scenes.value
  return scenes.value.filter((scene) => `${groupLabel(scene)} ${scene}`.toLowerCase().includes(words))
})
const enabled = computed(() => enabledIn(props.snapshot, props.name))
const manifest = computed(() => manifestOf(props.snapshot, props.name))
const canEdit = computed(
  () => enabled.value && !(manifest.value?.source?.candidate && !manifest.value?.source?.installed),
)

const compatibleEditable = computed(() =>
  scenes.value.filter(
    (scene) =>
      props.snapshot.scenes[scene].saved !== null &&
      (!platforms.value || platforms.value.includes(scene.split(':')[0])),
  ),
)
const allEnabled = computed(
  () =>
    compatibleEditable.value.length > 0 &&
    compatibleEditable.value.every((scene) => used.value.includes(scene)),
)

const pendingMap = ref<Record<string, boolean>>({})
const hasPendingSingles = computed(() => Object.keys(pendingMap.value).length > 0)
let writeQueue: Promise<void> = Promise.resolve()

function setPending(scene: string, value: boolean | undefined) {
  const next = { ...pendingMap.value }
  if (value === undefined) delete next[scene]
  else next[scene] = value
  pendingMap.value = next
}

async function toggle(scene: string, on: boolean) {
  const currentSnapshot = client.getQueryData<PluginsSnapshot>(keys.plugins.all()) ?? props.snapshot
  const entry = currentSnapshot.scenes[scene]
  if (!entry || entry.saved === null) return
  if (!on && entry.memory_plugin.saved === props.name && !(await confirmMemorySwitch())) return

  setPending(scene, on)
  writeQueue = writeQueue.then(async () => {
    try {
      const latest = client.getQueryData<PluginsSnapshot>(keys.plugins.all()) ?? props.snapshot
      const target = latest.scenes[scene]
      if (!target || target.saved === null) return
      const current = target.saved
      const next = on
        ? [...current.filter((item) => item !== props.name), props.name]
        : current.filter((item) => item !== props.name)
      const keep = (value: string | null) => (on || value !== props.name ? value : null)
      const memory = {
        memory_plugin: keep(target.memory_plugin.saved),
        recap_plugin: keep(target.recap_plugin.saved),
      }
      const result = await pluginsApi.putScene(scene, next, memory)
      client.setQueryData(keys.plugins.all(), result)
      void client.invalidateQueries({ queryKey: keys.plugins.health() })
      void readPendingRestart()
      toast.success(t('common.saved'))
    } catch (error) {
      toast.error(t('plugins.failed'), {
        detail: describeError(error, t('ui.error.network')).message,
      })
      void state.snapshot.refetch()
    } finally {
      setPending(scene, undefined)
    }
  })
}

const batchBusy = ref<'all' | 'none' | null>(null)
async function setAll(on: boolean) {
  if (!canEdit.value) return
  if (
    !on &&
    used.value.some((scene) => props.snapshot.scenes[scene]?.memory_plugin.saved === props.name) &&
    !(await confirmMemorySwitch())
  )
    return
  const next = on ? [...new Set([...used.value, ...compatibleEditable.value])] : []
  batchBusy.value = on ? 'all' : 'none'
  try {
    await state.run(`scenes:${props.name}`, () => pluginsApi.putPluginScenes(props.name, next), {
      success: t('common.saved'),
    })
  } finally {
    batchBusy.value = null
  }
}

const isMemory = (scene: string) => props.snapshot.scenes[scene]?.memory_plugin.saved === props.name
const isRecap = (scene: string) => props.snapshot.scenes[scene]?.recap_plugin.saved === props.name
</script>

<template>
  <div class="flex min-w-0 max-w-3xl flex-col gap-3">
    <EmptyState v-if="!scenes.length" :icon="MessagesSquare" :title="t('plugins.scenes.none')" compact />
    <template v-else>
      <p v-if="!enabled" class="rounded-md bg-fill px-3 py-2 text-sm text-muted">
        {{ t('plugins.scenes.enableFirst') }}
      </p>
      <div class="flex flex-wrap items-center gap-2">
        <div v-if="scenes.length > 5" class="w-full sm:w-64">
          <Input
            v-model="search"
            type="search"
            size="sm"
            :icon="Search"
            :placeholder="t('plugins.form.searchGroups')"
            :aria-label="t('plugins.form.searchGroups')"
            clearable
          />
        </div>
        <p class="text-sm text-muted tabular">
          {{ t('plugins.scenes.count', { n: used.length, total: scenes.length }) }}
        </p>
        <div v-if="canEdit" class="ml-auto flex items-center gap-1">
          <Button
            size="sm"
            variant="ghost"
            :loading="batchBusy === 'all'"
            :disabled="allEnabled || batchBusy !== null || hasPendingSingles || state.busy.value !== null"
            @click="setAll(true)"
          >
            {{ t('plugins.scenes.enableAll') }}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            :loading="batchBusy === 'none'"
            :disabled="!used.length || batchBusy !== null || hasPendingSingles || state.busy.value !== null"
            @click="setAll(false)"
          >
            {{ t('plugins.scenes.disableAll') }}
          </Button>
        </div>
      </div>
      <p v-if="!filteredScenes.length" class="py-3 text-sm text-muted">{{ t('common.noResults') }}</p>
      <ul v-else class="flex list-none flex-col divide-y divide-line border-y border-line">
        <li v-for="scene in filteredScenes" :key="scene" class="flex items-center gap-3 py-3">
          <Avatar :name="groupLabel(scene)" shape="square" :size="32" />
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-1.5">
              <p class="truncate text-sm font-medium text-ink">{{ groupLabel(scene) }}</p>
              <Badge v-if="isMemory(scene)" tone="info">{{ t('plugins.scenes.memoryBadge') }}</Badge>
              <Badge v-if="isRecap(scene)" tone="info">{{ t('plugins.scenes.recapBadge') }}</Badge>
            </div>
            <p v-if="sceneSecondaryId(scene)" class="truncate font-mono text-xs text-muted tabular">
              {{ sceneSecondaryId(scene) }}
            </p>
          </div>
          <IconButton
            v-if="isMemory(scene) || isRecap(scene)"
            :icon="Settings2"
            size="sm"
            variant="ghost"
            :label="t('plugins.scenes.openSettings')"
            :to="groupsTarget(scene, 'settings')"
          />
          <Switch
            :model-value="scene in pendingMap ? pendingMap[scene] : used.includes(scene)"
            :loading="scene in pendingMap"
            :disabled="
              !canEdit ||
              batchBusy !== null ||
              state.busy.value !== null ||
              snapshot.scenes[scene].saved === null
            "
            :aria-label="t('plugins.scenes.useIn', { name: groupLabel(scene) })"
            @update:model-value="(value: boolean) => toggle(scene, value)"
          />
        </li>
      </ul>
    </template>
  </div>
</template>
