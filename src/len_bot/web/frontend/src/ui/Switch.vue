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
      class="group relative inline-flex shrink-0 items-center rounded-full bg-track p-0.5 transition-[background-color,opacity] duration-200 ease-out hover:bg-line-strong focus-visible:focus-ring data-[state=checked]:bg-brand data-[state=checked]:hover:bg-brand data-[state=checked]:hover:opacity-92 data-disabled:opacity-50 aria-busy:opacity-100"
      :class="size === 'sm' ? 'h-4.5 w-8' : 'h-5.5 w-10'"
    >
      <SwitchThumb
        class="flex items-center justify-center rounded-full bg-white text-muted shadow-thumb transition-transform duration-200 ease-spring group-enabled:group-active:scale-x-110 group-data-[state=checked]:text-brand"
        :class="
          size === 'sm'
            ? 'size-3.5 data-[state=checked]:translate-x-3.5'
            : 'size-4.5 data-[state=checked]:translate-x-4.5'
        "
      >
        <Spinner v-if="loading" :size="size === 'sm' ? 10 : 12" />
      </SwitchThumb>
    </SwitchRoot>
    <span
      v-if="$slots.default"
      class="min-w-0 text-base text-ink"
      :class="field.disabled.value && 'opacity-60'"
    >
      <slot />
    </span>
  </label>
</template>
