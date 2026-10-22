<script setup lang="ts">
import { isolatedSource } from '../api/trials'
import ChatPanel from './playground/chat/ChatPanel.vue'
</script>

<template>
  <ChatPanel :source="isolatedSource" />
</template>
