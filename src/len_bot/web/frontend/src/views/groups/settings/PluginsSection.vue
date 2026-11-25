<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { ArrowUpRight } from '@lucide/vue'
import { commandRuleKey, pluginTitle } from '../../../api/plugins'
import Avatar from '../../../ui/Avatar.vue'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import FormSection from '../../../ui/FormSection.vue'
import Select from '../../../ui/Select.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Switch from '../../../ui/Switch.vue'
import { useForm } from './form'

const props = defineProps<{ scene: string }>()

const { t, te } = useI18n()
const form = useForm()
const scenePlatform = computed(() => props.scene.split(':')[0])
const platformLabel = (platform: string) =>
  te(`plugins.chatPlatforms.${platform}`) ? t(`plugins.chatPlatforms.${platform}`) : platform

/** Plugins the host loads; a group can only turn on those. Ones already on here stay listed. */
const items = computed(() => {
  const snapshot = form.plugins.data
  if (!snapshot) return []
  const loaded = Object.keys(snapshot.saved.plugins).filter((name) => !snapshot.saved.disabled.includes(name))
  const names = [...new Set([...loaded, ...(snapshot.scenes[props.scene]?.saved ?? [])])].sort()
  return names.map((name) => {
    const running = snapshot.running.plugins.find((item) => item.name === name)
    const manifest = snapshot.available[name]?.length === 1 ? snapshot.available[name][0] : undefined
    const title = pluginTitle(snapshot, name)
    const chatPlatforms = running?.chat_platforms ?? manifest?.chat_platforms ?? null
    const compatible = !chatPlatforms || chatPlatforms.includes(scenePlatform.value)
    const commands = (running?.commands ?? [])
      .filter((cmd) => !cmd.disabled)
      .map((cmd) => commandRuleKey(cmd.name))
    const toolsCount = running?.tools.length ?? 0
    const rulesCount = (running?.rules ?? []).filter((rule) => !rule.disabled).length
    const memoryEntries = running?.memory_entries ?? []
    const failed = running?.status === 'failed' || running?.health?.level === 'failed'
    const degraded =
      !failed && (running?.health?.level === 'degraded' || (running?.health?.errors_last_hour ?? 0) > 0)
    return {
      name,
      title,
      loaded: loaded.includes(name),
      failed,
      degraded,
      hasError: failed || degraded,
      chatPlatforms,
      compatible,
      commands,
      toolsCount,
      rulesCount,
      hasMemory: memoryEntries.includes('recall') || memoryEntries.includes('memory_tool'),
      hasRecap: memoryEntries.includes('compact'),
    }
  })
})
function toggle(name: string, on: boolean) {
  const list = form.draft.plugins.filter((item) => item !== name)
  form.draft.plugins = on ? [...list, name] : list
  // A plugin switched off here stops being this group's memory or recap.
  if (!on && form.draft.memory.memory_plugin === name) form.draft.memory.memory_plugin = null
  if (!on && form.draft.memory.recap_plugin === name) form.draft.memory.recap_plugin = null
}

/** Select options cannot be empty; this stands for the native implementation. */
const NATIVE = '*'
/** Enabled plugins offering the entry, and the saved choice even while its plugin is not running. */
function choices(entry: 'recall' | 'compact', saved: string | null) {
  const snapshot = form.plugins.data
  const offering = (snapshot?.running.plugins ?? [])
    .filter((item) => item.memory_entries.includes(entry) && form.draft?.plugins.includes(item.name))
    .map((item) => item.name)
  const names = [...new Set([...offering, ...(saved ? [saved] : [])])].sort()
  return [
    { value: NATIVE, label: t('groups.settings.plugins.native') },
    ...names.map((name) => ({ value: name, label: pluginTitle(snapshot, name) })),
  ]
}
const memoryOptions = computed(() => choices('recall', form.draft?.memory.memory_plugin ?? null))
const recapOptions = computed(() => choices('compact', form.draft?.memory.recap_plugin ?? null))
const memory = computed({
  get: () => form.draft?.memory.memory_plugin ?? NATIVE,
  set: (value: string) => form.draft && (form.draft.memory.memory_plugin = value === NATIVE ? null : value),
})
const recap = computed({
  get: () => form.draft?.memory.recap_plugin ?? NATIVE,
  set: (value: string) => form.draft && (form.draft.memory.recap_plugin = value === NATIVE ? null : value),
})
</script>

<template>
  <FormSection id="plugins" :title="t('groups.settings.plugins.section')" :columns="1">
    <template #actions>
      <Button size="sm" variant="ghost" :icon-right="ArrowUpRight" :to="{ name: 'host-plugins' }">
        {{ t('groups.settings.plugins.manage') }}
      </Button>
    </template>
    <Skeleton v-if="form.plugins.isPending" :lines="2" />
    <ErrorNote
      v-else-if="form.plugins.isError"
      :title="t('groups.settings.plugins.readFailed')"
      :error="form.plugins.error"
      :retry="form.plugins.refetch"
    />
    <p v-else-if="!items.length" class="text-sm text-muted">{{ t('groups.settings.plugins.empty') }}</p>
    <ul v-else class="flex flex-col divide-y divide-line">
      <li v-for="item in items" :key="item.name" class="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
        <span class="mt-0.5 flex shrink-0" aria-hidden="true">
          <Avatar :name="item.name" shape="square" :size="32" />
        </span>
        <div class="flex min-w-0 flex-1 flex-col gap-1.5">
          <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
            <RouterLink
              :to="{
                name: 'host-plugins',
                query: item.hasError ? { item: item.name, part: 'logs' } : { item: item.name },
              }"
              class="min-w-0 truncate rounded-sm text-sm font-medium text-ink transition-colors hover:text-primary hover:underline focus-visible:focus-ring"
            >
              {{ item.title }}
            </RouterLink>
            <span v-if="item.title !== item.name" class="truncate font-mono text-xs text-subtle">
              {{ item.name }}
            </span>
            <Badge v-if="!item.loaded" tone="warning" size="sm">
              {{ t('groups.settings.plugins.notLoaded') }}
            </Badge>
            <Badge v-else-if="item.failed" tone="error" size="sm">
              {{ t('groups.settings.plugins.failed') }}
            </Badge>
            <Badge v-else-if="item.degraded" tone="warning" size="sm">
              {{ t('groups.settings.plugins.degraded') }}
            </Badge>
          </div>
          <div
            v-if="
              item.commands.length ||
              item.toolsCount ||
              item.rulesCount ||
              item.hasMemory ||
              item.hasRecap ||
              item.chatPlatforms?.length
            "
            class="flex flex-wrap items-center gap-1.5"
          >
            <code
              v-for="cmd in item.commands.slice(0, 3)"
              :key="cmd"
              class="rounded-xs bg-code px-1.5 py-0.5 font-mono text-2xs text-ink-2"
            >
              {{ cmd }}
            </code>
            <Badge v-if="item.commands.length > 3" size="sm" class="tabular">
              +{{ item.commands.length - 3 }}
            </Badge>
            <Badge v-if="item.toolsCount" size="sm" class="tabular">
              {{ t('groups.settings.plugins.toolsCount', { n: item.toolsCount }) }}
            </Badge>
            <Badge v-if="item.rulesCount" size="sm" class="tabular">
              {{ t('groups.settings.plugins.rulesCount', { n: item.rulesCount }) }}
            </Badge>
            <Badge v-if="item.hasMemory" size="sm" tone="info">
              {{ t('groups.settings.plugins.memoryBadge') }}
            </Badge>
            <Badge v-if="item.hasRecap" size="sm" tone="info">
              {{ t('groups.settings.plugins.recapBadge') }}
            </Badge>
            <Badge
              v-for="platform in item.chatPlatforms ?? []"
              :key="`p:${platform}`"
              :tone="item.compatible ? 'neutral' : 'warning'"
              size="sm"
            >
              {{ platformLabel(platform) }}
            </Badge>
          </div>
        </div>
        <div class="shrink-0 pt-0.5">
          <Switch
            :model-value="form.draft.plugins.includes(item.name)"
            :disabled="!item.compatible && !form.draft.plugins.includes(item.name)"
            :aria-label="item.title"
            @update:model-value="(value: boolean) => toggle(item.name, value)"
          />
        </div>
      </li>
    </ul>
    <div
      v-if="memoryOptions.length > 1 || recapOptions.length > 1"
      class="grid gap-4 sm:grid-cols-2"
      :class="items.length > 0 && 'border-t border-line pt-4'"
    >
      <Field v-if="memoryOptions.length > 1" :label="t('groups.settings.plugins.memory')">
        <Select v-model="memory" :options="memoryOptions" />
      </Field>
      <Field v-if="recapOptions.length > 1" :label="t('groups.settings.plugins.recap')">
        <Select v-model="recap" :options="recapOptions" />
      </Field>
    </div>
  </FormSection>
</template>
