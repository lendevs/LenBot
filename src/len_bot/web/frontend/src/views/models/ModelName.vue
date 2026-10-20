<script setup lang="ts">
import { useId } from 'vue'
import type { ListedModel } from '../../api/models'
import Input from '../../ui/Input.vue'

/** A model name typed freely, suggesting the models read from the provider. */
const model = defineModel<string>({ required: true })
defineProps<{ models?: ListedModel[]; placeholder?: string }>()

const list = useId()
</script>

<template>
  <Input v-model="model" mono :placeholder="placeholder" :list="models?.length ? list : undefined" autocomplete="off" />
  <datalist v-if="models?.length" :id="list">
    <option v-for="item in models" :key="item.id" :value="item.id">{{ item.name !== item.id ? item.name : '' }}</option>
  </datalist>
</template>
