<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { SlidersHorizontal } from '@lucide/vue'
import type { ConfigField } from '../../../api/plugins'
import EmptyState from '../../../ui/EmptyState.vue'
import SchemaForm from '../schema/SchemaForm.vue'
import type { Draft } from '../schema/config'

const draft = defineModel<Draft>({ required: true })
defineProps<{
  fields: ConfigField[]
  /** False when the plugin's folder cannot be read, so its parameters are unknown. */
  readable: boolean
  sceneChoices: string[]
  configured: Record<string, boolean>
  problems: Record<string, string>
}>()

const { t } = useI18n()
</script>

<template>
  <div class="min-w-0">
    <SchemaForm
      v-if="readable && fields.length"
      v-model="draft"
      :fields="fields"
      :scene-choices="sceneChoices"
      :configured="configured"
      :problems="problems"
    />
    <EmptyState
      v-else
      :icon="SlidersHorizontal"
      :title="readable ? t('plugins.detail.noFields') : t('plugins.detail.unreadable')"
      compact
    />
  </div>
</template>
