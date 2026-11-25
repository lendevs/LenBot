<script setup lang="ts">
import Collapsible from '../../../ui/Collapsible.vue'

/** Fields most roles leave alone, folded under one heading at the end of a role tab. */
const open = defineModel<boolean>({ default: false })
defineProps<{ title: string; count?: number; dot?: 'warning' | 'error' | boolean }>()
</script>

<template>
  <Collapsible
    v-model:open="open"
    :title="title"
    :count="count"
    :dot="dot"
    content-class="flex flex-col gap-8"
  >
    <slot />
  </Collapsible>
</template>
