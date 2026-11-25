<script setup lang="ts">
import Collapsible from '../../ui/Collapsible.vue'

/** Settings that rarely change, folded under one heading; opened from outside when one of them is wrong. */
const open = defineModel<boolean>({ default: false })
defineProps<{ title: string }>()
</script>

<template>
  <Collapsible v-model:open="open" :title="title" content-class="grid gap-x-5 gap-y-5 sm:grid-cols-2">
    <slot />
  </Collapsible>
</template>
