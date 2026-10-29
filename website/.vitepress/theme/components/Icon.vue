<script setup lang="ts">
import { icons } from '../icons'

withDefaults(defineProps<{ name: string; size?: number; stroke?: number }>(), { size: 18, stroke: 2 })
</script>

<template>
  <svg
    class="lb-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="stroke"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    v-html="icons[name]"
  />
</template>
