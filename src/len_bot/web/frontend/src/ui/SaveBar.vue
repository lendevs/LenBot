<script setup lang="ts">
import { computed, onActivated, onDeactivated, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEventListener } from '@vueuse/core'
import { ChevronRight } from '@lucide/vue'
import Button from './Button.vue'
import CodeBlock from './CodeBlock.vue'

const props = withDefaults(
  defineProps<{
    dirty: boolean
    saving?: boolean
    /** Error text of the last failed save, kept until the next attempt. */
    error?: string | null
    /** Optional full error body shown when expanded. */
    rawError?: string | null
    /** Blocks saving, such as when a required field is empty. */
    invalid?: boolean
    /** Text of the save button when saving also performs another step. */
    saveLabel?: string
  }>(),
  { error: null, rawError: null, saveLabel: undefined },
)
const emit = defineEmits<{ save: []; discard: [] }>()

const { t } = useI18n()
const mac = /Mac|iPhone|iPad/.test(navigator.platform)
const canSave = computed(() => props.dirty && !props.saving && !props.invalid)
const hasRaw = computed(() =>
  Boolean(props.error && props.rawError && props.rawError.trim() && props.rawError !== props.error),
)
const showRaw = ref(false)
watch([() => props.error, () => props.rawError], () => (showRaw.value = false))
// A bar inside a hidden KeepAlive page keeps its draft but must not answer the shortcut.
const active = ref(true)
onActivated(() => (active.value = true))
onDeactivated(() => (active.value = false))

useEventListener(window, 'keydown', (event: KeyboardEvent) => {
  if (event.key.toLowerCase() !== 's' || !(mac ? event.metaKey : event.ctrlKey)) return
  if (!props.dirty || !active.value) return
  event.preventDefault()
  if (canSave.value) emit('save')
})
</script>

<template>
  <Transition name="ui-rise">
    <div
      v-if="dirty || saving"
      class="sticky bottom-3 z-(--z-top) mx-auto mt-6 flex w-full max-w-3xl flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-line-strong bg-surface-raised py-2.5 pr-2.5 pl-3.5 shadow-float sm:bottom-4"
      role="region"
      :aria-label="t('common.unsaved')"
    >
      <div class="flex min-w-36 flex-1 items-center gap-2.5">
        <span
          class="size-2 shrink-0 rounded-full"
          :class="error ? 'bg-error' : 'bg-warning'"
          aria-hidden="true"
        />
        <div class="min-w-0 flex-1">
          <p
            class="min-w-0 text-sm"
            :class="error ? 'line-clamp-2 font-medium text-error' : 'truncate text-ink-2'"
            :title="error ?? undefined"
          >
            {{ error ?? t('common.unsaved') }}
          </p>
          <button
            v-if="hasRaw"
            type="button"
            class="mt-0.5 inline-flex cursor-pointer items-center gap-0.5 rounded-sm text-xs font-medium text-muted transition-colors hover:text-ink focus-visible:focus-ring"
            :aria-expanded="showRaw"
            @click="showRaw = !showRaw"
          >
            <ChevronRight
              :size="13"
              class="transition-transform duration-150"
              :class="showRaw && 'rotate-90'"
              aria-hidden="true"
            />
            {{ t('common.rawError') }}
          </button>
        </div>
      </div>
      <div class="ml-auto flex shrink-0 items-center gap-2">
        <Button variant="ghost" size="sm" :disabled="saving" @click="emit('discard')">
          {{ t('common.discard') }}
        </Button>
        <Button variant="primary" size="sm" :loading="saving" :disabled="!canSave" @click="emit('save')">
          {{ saving ? t('common.saving') : (saveLabel ?? t('common.save')) }}
          <span v-if="!saving" class="ml-0.5 text-2xs font-medium opacity-75 max-sm:hidden">
            {{ mac ? '⌘S' : 'Ctrl S' }}
          </span>
        </Button>
      </div>
      <div v-if="showRaw && hasRaw" class="w-full pt-1">
        <CodeBlock :code="rawError!" :max-lines="10" />
      </div>
    </div>
  </Transition>
</template>
