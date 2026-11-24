<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowRight, MessagesSquare, Plus, Search } from '@lucide/vue'
import { hostApi, type HostState, type WakeLevel } from '../../api/host'
import { host, readHostState } from '../../api/hostStore'
import { formatNumber } from '../../i18n/format'
import { groupLabel, groupSecondaryId } from '../../layouts/shell/scenes'
import Avatar from '../../ui/Avatar.vue'
import Button from '../../ui/Button.vue'
import EmptyState from '../../ui/EmptyState.vue'
import Input from '../../ui/Input.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import StatusDot from '../../ui/StatusDot.vue'
import Switch from '../../ui/Switch.vue'
import { describeError } from '../../ui/errors'
import { toast } from '../../ui/toast'
import { groupsTarget } from '../groups/route'
import { statusTones, useStatusLabel } from '../groups/status'

const { t } = useI18n()
const statusLabel = useStatusLabel()
const state = computed(() => host.state as HostState)
const query = ref('')
const shown = computed(() => {
  const terms = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!terms.length) return state.value.scenes
  return state.value.scenes.filter((item) => {
    const haystack = `${groupLabel(item.scene)} ${item.scene} ${item.persona.name}`.toLowerCase()
    return terms.every((term) => haystack.includes(term))
  })
})
const members = (scene: string) => (host.members as Record<string, number>)[scene]

/** Per-scene in-flight toggles so switching one group never locks controls on other groups. */
const pendingOpen = reactive(new Map<string, boolean>())
const pendingChat = reactive(new Map<string, boolean>())
const pendingLevel = reactive(new Map<string, WakeLevel>())

async function toggleOpen(scene: string, enabled: boolean) {
  if (pendingOpen.has(scene)) return
  pendingOpen.set(scene, enabled)
  try {
    await hostApi.setOpen(scene, enabled)
    toast.success(t(enabled ? 'groups.opened' : 'groups.closed', { name: groupLabel(scene) }))
  } catch (error) {
    toast.error(t('groups.openFailed'), { detail: describeError(error, t('ui.error.network')).message })
  } finally {
    await readHostState()
    pendingOpen.delete(scene)
  }
}
async function toggleChat(scene: string, enabled: boolean) {
  if (pendingChat.has(scene)) return
  pendingChat.set(scene, enabled)
  try {
    await hostApi.setChat(scene, enabled)
    toast.success(t(enabled ? 'groups.chatOn' : 'groups.chatOff', { name: groupLabel(scene) }))
  } catch (error) {
    toast.error(t('groups.chatFailed'), { detail: describeError(error, t('ui.error.network')).message })
  } finally {
    await readHostState()
    pendingChat.delete(scene)
  }
}
async function changeLevel(scene: string, value: WakeLevel) {
  if (pendingLevel.has(scene)) return
  pendingLevel.set(scene, value)
  try {
    await hostApi.setWakeLevel(scene, value)
  } catch (error) {
    toast.error(t('overview.groups.levelFailed'), {
      detail: describeError(error, t('ui.error.network')).message,
    })
  } finally {
    await readHostState()
    pendingLevel.delete(scene)
  }
}

const opening = (scene: string) => pendingOpen.has(scene)
const isOpen = (item: HostState['scenes'][number]) =>
  pendingOpen.has(item.scene) ? pendingOpen.get(item.scene)! : item.scene_open
const switching = (scene: string) => pendingChat.has(scene)
const chatOn = (item: HostState['scenes'][number]) =>
  pendingChat.has(item.scene) ? pendingChat.get(item.scene)! : item.chat_enabled

const levels = computed(() =>
  (['active', 'moderate', 'quiet'] as const).map((value) => ({
    value,
    label: t(`overview.groups.levels.${value}`),
  })),
)
const leveling = (scene: string) => pendingLevel.has(scene)
const levelOf = (item: HostState['scenes'][number]): WakeLevel | '' =>
  pendingLevel.has(item.scene) ? pendingLevel.get(item.scene)! : (item.wake_level ?? '')
</script>

<template>
  <section class="flex min-w-0 flex-col gap-3">
    <div class="flex items-center justify-between gap-2">
      <h2 class="flex items-center gap-2 text-base font-semibold text-ink">
        {{ t('overview.groups.title') }}
        <span v-if="state.scenes.length" class="text-xs font-normal text-muted tabular">
          {{ formatNumber(state.scenes.length) }}
        </span>
      </h2>
      <Button size="sm" variant="ghost" :icon-right="ArrowRight" :to="groupsTarget()">
        {{ t('overview.groups.manage') }}
      </Button>
    </div>
    <div v-if="!state.scenes.length" class="border-y border-line">
      <EmptyState :icon="MessagesSquare" :title="t('groups.empty')" compact>
        <Button variant="primary" size="sm" :icon="Plus" :to="groupsTarget()">{{ t('groups.add') }}</Button>
      </EmptyState>
    </div>
    <template v-else>
      <Input
        v-if="state.scenes.length > 4"
        v-model="query"
        type="search"
        size="sm"
        :icon="Search"
        clearable
        :placeholder="t('groups.search')"
        :aria-label="t('groups.search')"
      />
      <ul class="flex list-none flex-col divide-y divide-line border-y border-line">
        <li v-for="item in shown" :key="item.scene" class="flex min-w-0 flex-col py-3">
          <div class="flex min-w-0 items-center gap-3">
            <RouterLink
              :to="groupsTarget(item.scene)"
              class="group link-plain flex min-w-0 flex-1 items-center gap-3 rounded-md focus-visible:focus-ring"
            >
              <Avatar :name="groupLabel(item.scene)" shape="square" :size="32" />
              <span class="min-w-0 flex-1">
                <span class="flex min-w-0 items-baseline gap-2">
                  <span
                    class="truncate text-sm font-medium transition-colors group-hover:text-primary"
                    :class="!item.chat_enabled || !isOpen(item) ? 'text-muted' : 'text-ink'"
                  >
                    {{ groupLabel(item.scene) }}
                  </span>
                  <span
                    v-if="groupSecondaryId(item.scene)"
                    class="shrink-0 font-mono text-xs text-subtle tabular"
                  >
                    {{ groupSecondaryId(item.scene) }}
                  </span>
                </span>
                <span class="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-muted tabular">
                  <StatusDot :tone="statusTones[item.chat_status.status]" />
                  <span class="truncate">
                    {{
                      [
                        statusLabel(item.chat_status, item.timezone),
                        members(item.scene) === undefined
                          ? ''
                          : t('groups.members', { n: formatNumber(members(item.scene)!) }),
                        item.persona.name,
                      ]
                        .filter(Boolean)
                        .join(' · ')
                    }}
                  </span>
                </span>
              </span>
            </RouterLink>
            <Switch
              :model-value="isOpen(item)"
              :loading="opening(item.scene)"
              :disabled="!state.connection.accepting || opening(item.scene)"
              :aria-label="t('overview.groups.open', { name: groupLabel(item.scene) })"
              @update:model-value="(enabled: boolean) => void toggleOpen(item.scene, enabled)"
            />
          </div>
          <div class="ui-grid-collapse" :data-open="isOpen(item) ? 'true' : 'false'" :inert="!isOpen(item)">
            <div>
              <div class="flex min-w-0 flex-wrap items-center gap-2 pt-2.5 pl-11">
                <SegmentedControl
                  :model-value="levelOf(item)"
                  :options="levels"
                  size="sm"
                  :disabled="leveling(item.scene) || opening(item.scene) || !isOpen(item)"
                  :label="t('overview.groups.level', { name: groupLabel(item.scene) })"
                  @update:model-value="(value) => value && void changeLevel(item.scene, value as WakeLevel)"
                />
                <Button
                  size="sm"
                  :variant="chatOn(item) ? 'secondary' : 'ghost'"
                  :loading="switching(item.scene)"
                  :disabled="!state.connection.accepting || opening(item.scene) || !isOpen(item)"
                  :aria-pressed="chatOn(item)"
                  :title="t(chatOn(item) ? 'overview.groups.chatHint' : 'overview.groups.pluginsHint')"
                  :aria-label="t('overview.groups.chat', { name: groupLabel(item.scene) })"
                  @click="void toggleChat(item.scene, !chatOn(item))"
                >
                  {{ t(chatOn(item) ? 'overview.groups.modeChat' : 'overview.groups.modePlugins') }}
                </Button>
              </div>
            </div>
          </div>
        </li>
        <li v-if="!shown.length" class="py-6 text-center text-sm text-muted">
          {{ t('common.noResults') }}
        </li>
      </ul>
    </template>
  </section>
</template>
