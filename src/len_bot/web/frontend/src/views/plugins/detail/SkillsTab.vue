<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { ArrowUpRight, BookOpen } from '@lucide/vue'
import type { RunningPlugin } from '../../../api/plugins'
import Button from '../../../ui/Button.vue'

defineProps<{ running: RunningPlugin }>()

const { t } = useI18n()
</script>

<template>
  <section class="flex min-w-0 max-w-3xl flex-col gap-3">
    <header class="flex items-center justify-between gap-3">
      <h3 class="text-base font-semibold text-ink">{{ t('plugins.skills.title') }}</h3>
      <Button size="sm" variant="ghost" :icon-right="ArrowUpRight" :to="{ name: 'host-persona' }">
        {{ t('plugins.skills.perRole') }}
      </Button>
    </header>
    <ul class="flex list-none flex-col divide-y divide-line border-y border-line">
      <li v-for="skill in running.skills" :key="skill" class="flex items-center gap-2.5 py-2.5">
        <BookOpen :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
        <code class="font-mono text-sm text-ink">{{ skill }}</code>
      </li>
    </ul>
  </section>
</template>
