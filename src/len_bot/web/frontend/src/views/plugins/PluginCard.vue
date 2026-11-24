<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpCircle, CircleAlert, MessagesSquare, RefreshCw, Wrench } from '@lucide/vue'
import { pluginsApi, pluginTitle, type FieldValue, type PluginsSnapshot } from '../../api/plugins'
import Avatar from '../../ui/Avatar.vue'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import Switch from '../../ui/Switch.vue'
import { toast } from '../../ui/toast'
import { configBody, formProblems, initialDraft } from './schema/config'
import { usePluginsState } from './state'
import {
  configuredIn,
  descriptionOf,
  enabledIn,
  featureCount,
  isolationOf,
  manifestOf,
  permissionsOf,
  runningOf,
  scenesUsing,
  statusOf,
  statusTone,
  versionOf,
} from './view'

const props = defineProps<{ name: string; snapshot: PluginsSnapshot }>()
const emit = defineEmits<{ open: [] }>()

const { t } = useI18n()
const state = usePluginsState()
const title = computed(() => pluginTitle(props.snapshot, props.name))
const manifest = computed(() => manifestOf(props.snapshot, props.name))
const source = computed(() => manifest.value?.source ?? null)
const candidate = computed(() => source.value?.candidate ?? null)
const hasInitialCandidate = computed(() => Boolean(candidate.value && !source.value?.installed))
const health = computed(() => state.healthOf(props.name))
const status = computed(() => statusOf(props.snapshot, props.name, health.value))
const running = computed(() => runningOf(props.snapshot, props.name))
const configured = computed(() => configuredIn(props.snapshot, props.name))
const on = computed(() => enabledIn(props.snapshot, props.name))
const version = computed(() => versionOf(props.snapshot, props.name))
const groups = computed(() => scenesUsing(props.snapshot, props.name).length)
const features = computed(() => featureCount(running.value))
const permissions = computed(() => permissionsOf(props.snapshot, props.name))
const recent = computed(() => health.value?.errors_last_hour ?? 0)
const update = computed(
  () => props.snapshot.updates?.find((item) => item.name === props.name && !item.prepared) ?? null,
)

const fields = computed(() => manifest.value?.fields ?? [])
const saved = computed(() => props.snapshot.saved.plugins[props.name])
const configuredSecrets = computed(() =>
  Object.fromEntries(
    Object.entries(saved.value ?? {}).map(([key, item]) => [key, 'configured' in item && item.configured]),
  ),
)
const initial = computed(() => initialDraft(fields.value, saved.value))
const hasMissingRequired = computed(
  () => Object.keys(formProblems(fields.value, initial.value, configuredSecrets.value, t)).length > 0,
)

const showSwitch = computed(
  () =>
    configured.value &&
    Boolean(manifest.value) &&
    !hasInitialCandidate.value &&
    (on.value || !hasMissingRequired.value),
)
const canReload = computed(
  () => status.value === 'failed' && manifest.value?.reload !== 'host' && !candidate.value,
)
const toggling = computed(() => state.isBusy(`toggle:${props.name}`))
const reloading = computed(() => state.isBusy(`reload:${props.name}`))
const pluginBusy = computed(() => state.pluginBusy(props.name))

async function toggle(next: boolean) {
  if (!next) {
    await state.run(`toggle:${props.name}`, () => pluginsApi.save(props.name, false), {
      success: t('plugins.detail.disabled'),
    })
    return
  }
  if (hasMissingRequired.value) {
    emit('open')
    return
  }
  let config: Record<string, FieldValue>
  try {
    config = configBody(fields.value, initial.value, saved.value, t)
  } catch {
    emit('open')
    return
  }
  await state.run(`toggle:${props.name}`, () => pluginsApi.save(props.name, true, config), {
    success: t('plugins.detail.enabled'),
  })
}

async function reload() {
  const result = await state.run(`reload:${props.name}`, () => pluginsApi.act(props.name, 'reload'))
  if (!result) return
  const failed = result.running.plugins.some((item) => item.name === props.name && item.status === 'failed')
  if (failed) toast.error(t('plugins.detail.actionFailed'))
  else toast.success(t('plugins.detail.done.reload'))
}
</script>

<template>
  <article
    class="relative flex flex-col gap-3 rounded-lg border border-line bg-surface p-4 shadow-card transition-[border-color,box-shadow] duration-150 hover:border-line-strong hover:shadow-hover"
  >
    <div class="flex items-start gap-3">
      <span class="flex shrink-0" :class="!on && 'opacity-60 grayscale'" aria-hidden="true">
        <Avatar :name="name" shape="square" :size="40" />
      </span>
      <div class="min-w-0 flex-1">
        <div class="flex min-w-0 items-baseline gap-1.5">
          <!-- The stretched button makes the whole card open the plugin. -->
          <button
            type="button"
            class="block max-w-full cursor-pointer truncate text-left text-base font-semibold after:absolute after:inset-0 after:rounded-lg focus-visible:outline-none focus-visible:after:focus-ring"
            :class="on ? 'text-ink' : 'text-ink-2'"
            @click="emit('open')"
          >
            {{ title }}
          </button>
          <span v-if="title !== name" class="min-w-0 shrink truncate font-mono text-xs text-subtle">
            {{ name }}
          </span>
        </div>
        <div class="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-subtle tabular">
          <span v-if="version">v{{ version }}</span>
          <Badge :tone="statusTone(status)" dot>{{ t(`plugins.status.${status}`) }}</Badge>
          <Badge v-if="candidate" tone="info">
            {{ t('plugins.card.candidate', { version: candidate.version }) }}
          </Badge>
          <span v-else-if="update" class="inline-flex items-center gap-1 font-medium text-info">
            <ArrowUpCircle :size="12" aria-hidden="true" />
            {{ t('plugins.card.update', { version: update.version }) }}
          </span>
        </div>
      </div>
      <div v-if="showSwitch" class="relative z-10 shrink-0 pt-0.5" @click.stop>
        <Switch
          size="sm"
          :model-value="on"
          :loading="toggling"
          :disabled="pluginBusy && !toggling"
          :aria-label="t('plugins.card.toggle', { name: title })"
          @update:model-value="toggle"
        />
      </div>
    </div>
    <p class="line-clamp-2 min-h-10 text-sm text-muted">{{ descriptionOf(snapshot, name) }}</p>
    <div
      class="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-line pt-3 text-xs text-muted tabular"
    >
      <span class="inline-flex items-center gap-1" :class="on && !groups && 'text-warning'">
        <MessagesSquare :size="14" aria-hidden="true" />
        {{
          groups
            ? t('plugins.card.groups', { n: groups }, groups)
            : on
              ? t('plugins.card.zeroGroups')
              : t('plugins.card.noGroups')
        }}
      </span>
      <span v-if="features" class="inline-flex items-center gap-1">
        <Wrench :size="14" aria-hidden="true" />
        {{ t('plugins.card.features', { n: features }, features) }}
      </span>
      <span v-if="recent" class="inline-flex items-center gap-1 text-error">
        <CircleAlert :size="14" aria-hidden="true" />
        {{ t('plugins.card.errors', { n: recent }, recent) }}
      </span>
      <Badge v-if="isolationOf(snapshot, name) === 'process'">
        {{ t('plugins.isolation.processShort') }}
      </Badge>
      <Badge v-if="permissions === null" tone="warning">{{ t('plugins.permissions.undeclaredShort') }}</Badge>
      <Button
        v-if="canReload"
        size="xs"
        variant="secondary"
        :icon="RefreshCw"
        :loading="reloading"
        :disabled="pluginBusy && !reloading"
        class="relative z-10 ml-auto"
        @click.stop="reload"
      >
        {{ t('plugins.card.reload') }}
      </Button>
    </div>
  </article>
</template>
