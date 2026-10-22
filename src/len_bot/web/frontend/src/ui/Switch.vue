<script setup lang="ts">
import { SwitchRoot, SwitchThumb } from 'reka-ui'
import Spinner from './Spinner.vue'
import { useFieldControl } from './field'

const model = defineModel<boolean>({ default: false })
const props = withDefaults(
  defineProps<{
    size?: 'sm' | 'md'
    /** The change is being saved: the switch keeps its new position and waits. */
    loading?: boolean
    id?: string
    disabled?: boolean
  }>(),
  { size: 'md', id: undefined },
)

const field = useFieldControl(props)
</script>

<template>
  <label
    class="inline-flex min-w-0 items-center gap-2.5"
    :class="field.disabled.value || loading ? 'cursor-not-allowed' : 'cursor-pointer'"
  >
    <SwitchRoot
      :id="field.id.value"
      v-model="model"
      :disabled="field.disabled.value || loading"
      :aria-busy="loading || undefined"
      class="group relative inline-flex shrink-0 items-center rounded-full bg-track p-0.5 transition-colors duration-200 ease-out focus-visible:focus-ring data-[state=checked]:bg-primary data-disabled:opacity-50 aria-busy:opacity-100"
      :class="size === 'sm' ? 'h-4.5 w-8' : 'h-5.5 w-10'"
    >
      <SwitchThumb
        class="flex items-center justify-center rounded-full bg-white text-primary shadow-[0_1px_2px_rgb(0_0_0/20%)] transition-transform duration-200 ease-spring group-active:scale-x-110"
        :class="
          size === 'sm'
            ? 'size-3.5 data-[state=checked]:translate-x-3.5'
            : 'size-4.5 data-[state=checked]:translate-x-4.5'
        "
      >
        <Spinner v-if="loading" :size="size === 'sm' ? 10 : 12" />
      </SwitchThumb>
    </SwitchRoot>
    <span v-if="$slots.default" class="min-w-0 text-base text-ink"><slot /></span>
  </label>
</template>
