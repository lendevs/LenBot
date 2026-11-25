<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronRight, CircleAlert, RotateCw } from '@lucide/vue'
import Button from './Button.vue'
import CodeBlock from './CodeBlock.vue'
import { describeError } from './errors'

const props = withDefaults(
  defineProps<{
    /** Short summary of what failed. */
    title?: string
    error: unknown
    retry?: () => unknown
  }>(),
  { title: undefined, retry: undefined },
)

const { t } = useI18n()
const showRaw = ref(false)
const retrying = ref(false)
const described = computed(() => describeError(props.error, t('ui.error.network')))
const raw = computed(() => {
  const { status, raw } = described.value
  if (raw === null || raw === described.value.message) return null
  return status === null ? raw : `HTTP ${status}\n${raw}`
})
watch(raw, (value) => {
  if (!value) showRaw.value = false
})

async function runRetry() {
  if (!props.retry || retrying.value) return
  const result = props.retry()
  if (result && typeof (result as PromiseLike<unknown>).then === 'function') {
    retrying.value = true
    try {
      await result
    } finally {
      retrying.value = false
    }
  }
}
</script>

<template>
  <div
    role="alert"
    class="flex animate-fade items-start gap-3 rounded-lg border border-error-line bg-error-bg px-4 py-3 text-ink"
  >
    <CircleAlert :size="18" class="mt-0.5 shrink-0 text-error" aria-hidden="true" />
    <div class="min-w-0 flex-1">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <p class="min-w-0 text-sm font-semibold text-error">{{ title ?? t('ui.error.title') }}</p>
        <Button
          v-if="retry"
          size="xs"
          variant="ghost"
          :icon="RotateCw"
          :loading="retrying"
          class="-my-1 shrink-0"
          @click="runRetry"
        >
          {{ t('common.retry') }}
        </Button>
      </div>
      <p class="mt-0.5 text-sm break-words whitespace-pre-line text-ink-2">{{ described.message }}</p>
      <button
        v-if="raw"
        type="button"
        class="mt-1.5 inline-flex cursor-pointer items-center gap-0.5 rounded-sm text-xs font-medium text-muted transition-colors hover:text-ink focus-visible:focus-ring pointer-coarse:min-h-9"
        :aria-expanded="showRaw"
        @click="showRaw = !showRaw"
      >
        <ChevronRight
          :size="14"
          class="transition-transform duration-(--dur-1) ease-out"
          :class="showRaw && 'rotate-90'"
          aria-hidden="true"
        />
        {{ t('common.rawError') }}
      </button>
      <div v-if="raw" class="ui-grid-collapse" :data-open="showRaw ? 'true' : 'false'" :inert="!showRaw">
        <div>
          <div class="pt-2">
            <CodeBlock :code="raw" :max-lines="12" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
