<script setup lang="ts">
import { useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { CheckboxIndicator, CheckboxRoot } from 'reka-ui'
import { Check, ExternalLink } from '@lucide/vue'
import { setupApi } from '../../../api/setup'
import Badge from '../../../ui/Badge.vue'
import EmptyState from '../../../ui/EmptyState.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { useWizard } from '../wizard'

const { t, te } = useI18n()
const { draft } = useWizard()
const uid = useId()
const plugins = useQuery({ queryKey: ['setup', 'plugins'], queryFn: setupApi.plugins })

watch(
  () => plugins.data.value?.plugins,
  (list) => {
    if (!list) return
    const installed = new Set(list.filter((item) => item.installed).map((item) => item.name))
    if (draft.plugins.some((name) => installed.has(name))) {
      draft.plugins = draft.plugins.filter((name) => !installed.has(name))
    }
  },
  { immediate: true },
)

function toggle(name: string, on: boolean | 'indeterminate') {
  draft.plugins =
    on === true ? [...new Set([...draft.plugins, name])] : draft.plugins.filter((item) => item !== name)
}

const platformLabel = (platform: string) =>
  te(`plugins.chatPlatforms.${platform}`) ? t(`plugins.chatPlatforms.${platform}`) : platform
const permissionLabel = (name: string) =>
  te(`plugins.permissions.names.${name}`) ? t(`plugins.permissions.names.${name}`) : name
</script>

<template>
  <div class="flex flex-col gap-4">
    <Skeleton v-if="plugins.isPending.value" :lines="4" />
    <ErrorNote
      v-else-if="plugins.isError.value"
      :title="t('setup.plugins.readFailed')"
      :error="plugins.error.value"
      :retry="plugins.refetch"
    />
    <EmptyState v-else-if="!plugins.data.value?.plugins.length" :title="t('setup.plugins.none')" compact />
    <ul v-else class="flex list-none flex-col gap-2">
      <li v-for="item in plugins.data.value.plugins" :key="item.name" class="min-w-0">
        <label
          :for="`${uid}-${item.name}`"
          class="flex min-w-0 items-start gap-3 rounded-lg border px-3.5 py-3 transition-colors"
          :class="
            item.installed
              ? 'cursor-not-allowed border-line bg-fill/55 opacity-60'
              : draft.plugins.includes(item.name)
                ? 'cursor-pointer border-primary/50 bg-selected/45'
                : 'cursor-pointer border-line bg-surface hover:border-line-strong hover:bg-hover/40'
          "
        >
          <CheckboxRoot
            :id="`${uid}-${item.name}`"
            :model-value="item.installed || draft.plugins.includes(item.name)"
            :disabled="item.installed"
            class="mt-0.5 inline-flex size-4.5 shrink-0 items-center justify-center rounded-xs border border-line-strong bg-surface text-on-primary transition-[background-color,border-color,transform] duration-(--dur-1) ease-out hover:border-subtle focus-visible:focus-ring enabled:active:scale-95 disabled:cursor-not-allowed data-[state=checked]:border-primary data-[state=checked]:bg-primary"
            @update:model-value="(on) => !item.installed && toggle(item.name, on)"
          >
            <CheckboxIndicator class="inline-flex animate-[ui-pop-in_var(--dur-1)_var(--ease-spring)]">
              <Check :size="13" :stroke-width="3" aria-hidden="true" />
            </CheckboxIndicator>
          </CheckboxRoot>
          <div class="flex min-w-0 flex-1 flex-col gap-1.5">
            <div class="flex min-w-0 flex-wrap items-center gap-2">
              <span class="font-medium text-ink">{{ item.title }}</span>
              <Badge v-if="item.installed" tone="success">{{ t('setup.plugins.installed') }}</Badge>
              <a
                :href="item.repository"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex items-center gap-1 rounded-sm font-mono text-xs text-muted hover:text-ink focus-visible:focus-ring tabular"
                @click.stop
              >
                {{ item.version }}
                <ExternalLink :size="12" aria-hidden="true" />
              </a>
            </div>
            <p class="text-sm text-ink-2">{{ item.description }}</p>
            <div
              v-if="item.chat_platforms?.length || item.permissions === null || item.permissions?.length"
              class="flex flex-wrap gap-1.5"
            >
              <Badge v-for="platform in item.chat_platforms ?? []" :key="`p:${platform}`" tone="brand">
                {{ platformLabel(platform) }}
              </Badge>
              <Badge v-if="item.permissions === null" tone="warning">
                {{ t('plugins.permissions.undeclaredShort') }}
              </Badge>
              <Badge v-for="perm in item.permissions ?? []" :key="`perm:${perm}`">
                {{ permissionLabel(perm) }}
              </Badge>
            </div>
            <p v-if="item.error" class="text-xs break-words text-error">
              {{ t('setup.plugins.lastError', { error: item.error }) }}
            </p>
          </div>
        </label>
      </li>
    </ul>
  </div>
</template>
