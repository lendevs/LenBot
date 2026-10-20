<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Moon, Zap } from '@lucide/vue'
import type { Verdict } from '../../../api/timeline'
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
      </dl>
    </div>
  </Popover>
</template>
