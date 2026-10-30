<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Moon, Zap } from '@lucide/vue'
import { PART_NAMES, type Verdict } from '../../../api/timeline'
import { formatNumber } from '../../../i18n/format'
import Popover from '../../../ui/Popover.vue'
import { useLiveLabels } from './labels'

const props = defineProps<{ verdict: Verdict }>()

const { t } = useI18n()
const labels = useLiveLabels()
const title = computed(() =>
  props.verdict.woke && props.verdict.channel
    ? t('groups.live.verdict.woke', { channel: labels.channel(props.verdict.channel) })
    : t('groups.live.verdict.slept'),
)
const number = (value: number) => formatNumber(value, { maximumFractionDigits: 2 })
const signed = (value: number) => (value > 0 ? '+' : '') + number(value)
const parts = computed(() => {
  const value = props.verdict.parts
  return value
    ? PART_NAMES.filter((name) => value[name] !== 0).map((name) => [name, value[name]] as const)
    : []
})
</script>

<template>
  <Popover width="w-64">
    <template #trigger>
      <button
        type="button"
        class="inline-flex size-5 cursor-pointer items-center justify-center rounded-sm transition-colors hover:bg-hover focus-visible:focus-ring"
        :class="verdict.woke ? 'text-primary' : 'text-subtle opacity-70 hover:opacity-100'"
        :title="`${title} · ${verdict.reason}`"
        :aria-label="title"
      >
        <component :is="verdict.woke ? Zap : Moon" :size="12" aria-hidden="true" />
      </button>
    </template>
    <div class="flex flex-col gap-2 text-sm">
      <strong class="font-semibold" :class="verdict.woke ? 'text-primary' : 'text-ink'">{{ title }}</strong>
      <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt class="text-muted">{{ t('groups.live.verdict.reason') }}</dt>
        <dd class="min-w-0 break-words text-ink">{{ verdict.reason }}</dd>
        <template v-if="verdict.score !== null">
          <dt class="text-muted">{{ t('groups.live.verdict.score') }}</dt>
          <dd class="tabular">
            {{ number(verdict.score) }}
            <span v-if="verdict.threshold !== null" class="text-muted">
              / {{ t('groups.live.verdict.threshold') }} {{ number(verdict.threshold) }}
            </span>
          </dd>
        </template>
        <template v-if="verdict.effect_factor != null && verdict.effect_factor < 1">
          <dt class="text-muted">{{ t('groups.live.verdict.effect') }}</dt>
          <dd class="tabular">{{ number(verdict.effect_factor) }}</dd>
        </template>
      </dl>
      <template v-if="verdict.parts">
        <strong class="border-t border-line pt-2 text-xs font-semibold text-ink-2">
          {{ t('groups.live.verdict.parts.title') }} ·
          {{ t('groups.live.verdict.parts.messages', { n: verdict.parts.messages }) }}
        </strong>
        <dl class="grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 text-xs">
          <template v-for="[name, value] in parts" :key="name">
            <dt class="text-muted">{{ t(`groups.live.verdict.parts.${name}`) }}</dt>
            <dd class="text-right tabular">{{ signed(value) }}</dd>
          </template>
          <dt class="text-muted">{{ t('groups.live.verdict.parts.raw') }}</dt>
          <dd class="text-right font-medium tabular">{{ number(verdict.parts.raw) }}</dd>
          <dt class="text-muted">{{ t('groups.live.verdict.parts.activity') }}</dt>
          <dd class="text-right tabular">× {{ number(verdict.parts.activity) }}</dd>
        </dl>
      </template>
    </div>
  </Popover>
</template>
