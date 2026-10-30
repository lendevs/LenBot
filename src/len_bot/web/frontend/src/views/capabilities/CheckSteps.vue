<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Check, X } from '@lucide/vue'
import type { SandboxStep } from '../../api/capabilities'

defineProps<{ steps: SandboxStep[] }>()
const { t } = useI18n()
</script>

<template>
  <ul v-if="steps.length" class="flex w-full min-w-0 flex-col gap-2">
    <li v-for="item in steps" :key="item.step" class="flex min-w-0 flex-col gap-1">
      <span class="flex items-center gap-2 text-sm" :class="item.ok ? 'text-ink' : 'text-error'">
        <component :is="item.ok ? Check : X" :size="16" class="shrink-0" aria-hidden="true" />
        {{ t(`capabilities.worker.checkSteps.${item.step}`) }}
      </span>
      <pre
        v-if="!item.ok"
        class="ml-6 overflow-x-auto rounded-md bg-code px-3 py-2 text-xs whitespace-pre-wrap text-ink-2"
        >{{ item.detail }}</pre>
    </li>
  </ul>
</template>
