<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEventListener } from '@vueuse/core'
import Button from './Button.vue'

const props = withDefaults(
  defineProps<{
    dirty: boolean
    saving?: boolean
    /** Error text of the last failed save, kept until the next attempt. */
    error?: string | null
    /** Blocks saving, such as when a required field is empty. */
    invalid?: boolean
  }>(),
  { error: null },
)
const emit = defineEmits<{ save: []; discard: [] }>()

const { t } = useI18n()
const mac = /Mac|iPhone|iPad/.test(navigator.platform)
const canSave = computed(() => props.dirty && !props.saving && !props.invalid)

useEventListener(window, 'keydown', (event: KeyboardEvent) => {
  if (event.key.toLowerCase() !== 's' || !(mac ? event.metaKey : event.ctrlKey)) return
  if (!props.dirty) return
  event.preventDefault()
  if (canSave.value) emit('save')
})
</script>

<template>
  <Transition name="ui-rise">
    <div
      v-if="dirty || saving"
      class="sticky bottom-4 z-(--z-top) mx-auto mt-6 flex w-full max-w-3xl flex-wrap items-center gap-3 rounded-lg border border-line bg-surface-raised py-2.5 pr-2.5 pl-4 shadow-float"
      role="region"
      :aria-label="t('common.unsaved')"
    >
      <span
        class="size-2 shrink-0 rounded-full"
        :class="error ? 'bg-error' : 'bg-warning'"
        aria-hidden="true"
      />
      <p
        class="min-w-0 flex-1 truncate text-sm"
        :class="error ? 'text-error' : 'text-ink-2'"
        :title="error ?? undefined"
      >
        {{ error ?? t('common.unsaved') }}
      </p>
      <div class="flex items-center gap-2">
        <Button variant="ghost" size="sm" :disabled="saving" @click="emit('discard')">
          {{ t('common.discard') }}
        </Button>
        <Button variant="primary" size="sm" :loading="saving" :disabled="!canSave" @click="emit('save')">
          {{ saving ? t('common.saving') : t('common.save') }}
          <span v-if="!saving" class="ml-0.5 text-[11px] font-medium opacity-70 max-sm:hidden">
            {{ mac ? '⌘S' : 'Ctrl S' }}
          </span>
        </Button>
      </div>
    </div>
  </Transition>
</template>
