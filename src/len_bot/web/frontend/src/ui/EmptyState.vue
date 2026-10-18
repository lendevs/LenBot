<script setup lang="ts">
import type { Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { Inbox } from '@lucide/vue'

withDefaults(defineProps<{ title?: string; icon?: Component; compact?: boolean }>(), {
  title: undefined,
  icon: undefined,
})
const { t } = useI18n()
</script>

<template>
  <div
    class="flex animate-fade flex-col items-center justify-center gap-3 text-center"
    :class="compact ? 'px-4 py-6' : 'px-6 py-14'"
  >
    <span
      class="inline-flex items-center justify-center rounded-xl bg-fill text-subtle"
      :class="compact ? 'size-9' : 'size-12'"
    >
      <component :is="icon ?? Inbox" :size="compact ? 18 : 22" aria-hidden="true" />
    </span>
    <p class="text-base font-medium text-muted">{{ title ?? t('ui.empty.title') }}</p>
    <div v-if="$slots.default" class="mt-1 flex flex-wrap justify-center gap-2"><slot /></div>
  </div>
</template>
