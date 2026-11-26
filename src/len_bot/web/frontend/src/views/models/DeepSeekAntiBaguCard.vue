<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, Sparkles } from '@lucide/vue'
import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import { isDeepSeekFullyTuned, needsDeepSeekThinkingTune } from './deepseek'

const enabled = defineModel<boolean>({ required: true })
const props = withDefaults(
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
const emit = defineEmits<{
  tune: []
}>()
const { t } = useI18n()

const tuningState = computed(() => ({
  antiBagu: enabled.value,
  effort: props.effort,
  quickEffort: props.quickEffort,
  thinking: props.thinking,
}))
const needsThinkingTune = computed(() => enabled.value && needsDeepSeekThinkingTune(tuningState.value))
const fullyTuned = computed(() => isDeepSeekFullyTuned(tuningState.value))
</script>

<template>
  <div
    class="flex flex-col gap-3 rounded-lg border px-4 py-3.5 transition-colors duration-(--dur-2) sm:flex-row sm:items-center sm:justify-between sm:gap-4"
    :class="fullyTuned ? 'border-primary/35 bg-selected' : 'border-warning/40 bg-warning-bg shadow-card'"
  >
    <div class="flex min-w-0 items-start gap-3">
      <span
        class="mt-0.5 inline-flex size-8 shrink-0 items-center justify-center rounded-md bg-surface shadow-card"
        :class="fullyTuned ? 'text-primary' : 'text-warning'"
        aria-hidden="true"
      >
        <Sparkles :size="16" />
      </span>
      <div class="flex min-w-0 flex-col gap-1">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-sm font-semibold text-ink">{{ t('models.roles.antiBagu.title') }}</span>
          <Badge v-if="fullyTuned" tone="success" dot>
            {{ t('models.roles.antiBagu.activeBadge') }}
          </Badge>
          <Badge v-else-if="needsThinkingTune" tone="warning" dot pulse>
            {{ t('models.roles.antiBagu.partialBadge') }}
          </Badge>
          <Badge v-else tone="warning" dot pulse>
            {{ t('models.roles.antiBagu.recommendedBadge') }}
          </Badge>
        </div>
        <p class="text-xs leading-relaxed text-ink-2">
          {{
            t(
              fullyTuned
                ? 'models.roles.antiBagu.activeHint'
                : needsThinkingTune
                  ? 'models.roles.antiBagu.thinkingWarnHint'
                  : 'models.roles.antiBagu.recommendedHint',
            )
          }}
        </p>
      </div>
    </div>
    <div class="flex shrink-0 flex-wrap items-center gap-2 max-sm:w-full sm:justify-end sm:self-center">
      <Button
        v-if="!enabled"
        variant="primary"
        size="sm"
        :icon="Sparkles"
        class="max-sm:w-full"
        @click="emit('tune')"
      >
        {{ t('models.roles.antiBagu.applyTune') }}
      </Button>
      <template v-else-if="needsThinkingTune">
        <Button variant="primary" size="sm" :icon="Sparkles" class="max-sm:flex-1" @click="emit('tune')">
          {{ t('models.roles.antiBagu.fixThinking') }}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          :icon="Check"
          :aria-pressed="enabled"
          class="max-sm:flex-1"
          @click="enabled = false"
        >
          {{ t('models.roles.antiBagu.turnOff') }}
        </Button>
      </template>
      <Button
        v-else
        variant="secondary"
        size="sm"
        :icon="Check"
        :aria-pressed="enabled"
        class="max-sm:w-full"
        @click="enabled = false"
      >
        {{ t('models.roles.antiBagu.turnOff') }}
      </Button>
    </div>
  </div>
</template>
