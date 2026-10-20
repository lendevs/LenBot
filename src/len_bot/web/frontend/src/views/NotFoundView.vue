<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Home } from '@lucide/vue'
import { useAuth } from '../composables/useAuth.js'
import Button from '../ui/Button.vue'
import EmptyState from '../ui/EmptyState.vue'

const { t } = useI18n()
const auth = useAuth()
</script>

<template>
  <EmptyState :title="t('shell.notFound.message')">
    <Button variant="primary" :icon="Home" :to="auth.panelContext?.home ?? '/'">{{ t('shell.notFound.home') }}</Button>
  </EmptyState>
</template>
