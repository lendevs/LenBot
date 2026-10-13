<script setup>
import { computed, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { useUnsavedChanges } from '../../../composables/useUnsavedChanges.js'
import HostPage from '../../ui/HostPage.vue'
import PluginsSection from './PluginsSection.vue'

const route = useRoute()
const dirty = reactive({})
useUnsavedChanges(computed(() => Object.values(dirty).some(Boolean)), {
  keep: ['part'], onDiscard: () => { for (const key of Object.keys(dirty)) dirty[key] = false },
})
</script>

<template>
  <HostPage :title="route.query.item ? '' : '插件'" wide>
    <PluginsSection @dirty="value => dirty.plugins = value" />
  </HostPage>
</template>
