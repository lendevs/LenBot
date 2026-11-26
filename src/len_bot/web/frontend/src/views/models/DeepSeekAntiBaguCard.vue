<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Check, Sparkles } from '@lucide/vue'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'

const enabled = defineModel<boolean>({ required: true })
withDefaults(
  defineProps<{
    effort?: string | null
    quickEffort?: string | null
    thinking?: 'enabled' | 'disabled' | null
  }>(),
  {
    effort: null,
    quickEffort: null,
    thinking: null,
  },
)
defineEmits<{
  tune: []
}>()
const { t } = useI18n()
</script>

<template>
  <div
    class="flex flex-col gap-3 rounded-lg border px-4 py-3.5 transition-colors duration-(--dur-2) sm:flex-row sm:items-center sm:justify-between sm:gap-4"
    :class="enabled ? 'border-primary/35 bg-selected' : 'border-warning/40 bg-warning-bg shadow-card'"
  >
    <div class="flex min-w-0 items-start gap-3">
      <span
        class="mt-0.5 inline-flex size-8 shrink-0 items-center justify-center rounded-md bg-surface shadow-card"
        :class="enabled ? 'text-primary' : 'text-warning'"
        aria-hidden="true"
      >
        <Sparkles :size="16" />
      </span>
      <div class="flex min-w-0 flex-col gap-1">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-sm font-semibold text-ink">{{ t('models.roles.antiBagu.title') }}</span>
          <Badge v-if="enabled" tone="success" dot>{{ t('models.roles.antiBagu.activeBadge') }}</Badge>
          <Badge v-else tone="warning" dot pulse>{{ t('models.roles.antiBagu.recommendedBadge') }}</Badge>
        </div>
        <p class="text-xs leading-relaxed text-ink-2">
          {{ t(enabled ? 'models.roles.antiBagu.activeHint' : 'models.roles.antiBagu.recommendedHint') }}
        </p>
      </div>
    </div>
    <div class="flex shrink-0 items-center sm:self-center">
      <Button
        :variant="enabled ? 'secondary' : 'primary'"
        size="sm"
        :icon="enabled ? Check : Sparkles"
        :aria-pressed="enabled"
        class="max-sm:w-full"
        @click="enabled = !enabled"
      >
        {{ t(enabled ? 'models.roles.antiBagu.turnOff' : 'models.roles.antiBagu.turnOn') }}
      </Button>
    </div>
  </div>
</template>
