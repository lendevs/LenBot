<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Check, X } from '@lucide/vue'
import type { SandboxStep } from '../../api/capabilities'

defineProps<{ steps: SandboxStep[] }>()
const { t } = useI18n()
</script>

<template>
  <ul v-if="steps.length" class="flex w-full min-w-0 list-none flex-col gap-2">
    <li v-for="item in steps" :key="item.step" class="flex min-w-0 flex-col gap-1.5">
      <div class="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5 text-sm">
        <span
          class="inline-flex shrink-0 items-center gap-2"
          :class="item.ok ? 'text-ink' : 'font-medium text-error'"
        >
          <component
            :is="item.ok ? Check : X"
            :size="16"
            class="shrink-0"
            :class="item.ok ? 'text-success' : 'text-error'"
            aria-hidden="true"
          />
          {{ t(`capabilities.worker.checkSteps.${item.step}`) }}
        </span>
        <span v-if="item.ok && item.detail" class="min-w-0 break-words font-mono text-xs text-muted">
          {{ item.detail }}
        </span>
      </div>
      <pre
        v-if="!item.ok"
        class="ml-6 overflow-x-auto rounded-md border border-line bg-code px-3 py-2 font-mono text-xs leading-5 break-words whitespace-pre-wrap text-ink-2 scrollbar-thin"
        >{{ item.detail }}</pre>
    </li>
  </ul>
</template>
