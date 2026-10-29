<script setup lang="ts">
import { withBase } from 'vitepress'

// The README cards in public/readme, switched with the site's own light and dark class.
defineProps<{ name: string; alt: string; eager?: boolean }>()
</script>

<template>
  <span class="card-image">
    <img class="light-only" :src="withBase(`/readme/${name}.svg`)" :alt="alt" :loading="eager ? 'eager' : 'lazy'" />
    <img class="dark-only" :src="withBase(`/readme/${name}.dark.svg`)" :alt="alt" :loading="eager ? 'eager' : 'lazy'" />
  </span>
</template>

<style scoped>
.card-image { display: block; }
.card-image img { display: block; width: 100%; height: auto; border: 0; border-radius: 0; box-shadow: none; }
.dark-only { display: none !important; }
:global(.dark) .card-image .light-only { display: none !important; }
:global(.dark) .card-image .dark-only { display: block !important; }
</style>
