<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessageCircleQuestion } from '@lucide/vue'
import type { TaskQuestion } from '../../../api/tasks'
import { formatDuration } from '../../../i18n/format'
import Button from '../../../ui/Button.vue'
import RadioGroup from '../../../ui/RadioGroup.vue'
import Textarea from '../../../ui/Textarea.vue'
import { confirm } from '../../../ui/confirm'

const props = withDefaults(
  defineProps<{
    question: TaskQuestion
    canAnswer: boolean
    busy: boolean
    urgent?: boolean
    timeoutSeconds?: number | null
    disabledReason?: string | null
  }>(),
  { urgent: false, timeoutSeconds: null, disabledReason: null },
)
const emit = defineEmits<{
  answer: [body: { question_id: string; text?: string; confirmed?: boolean }]
  dirty: [value: boolean]
}>()

const { t } = useI18n()
const mac = /Mac|iPhone|iPad/.test(navigator.platform)
const text = ref('')
const choice = ref<string>()
const options = computed(() => (props.question.options ?? []).map((value) => ({ value, label: value })))
watch(
  () => Boolean(text.value.trim() || choice.value !== undefined),
  (value) => emit('dirty', value),
  { immediate: true },
)
// A new question starts empty.
watch(
  () => props.question.id,
  () => {
    text.value = ''
    choice.value = undefined
  },
)

async function decide(confirmed: boolean) {
  const sure = await confirm({
    title: t(confirmed ? 'groups.tasks.question.agreeTitle' : 'groups.tasks.question.refuseTitle'),
    message: props.question.title,
    confirmLabel: t(confirmed ? 'groups.tasks.question.agree' : 'groups.tasks.question.refuse'),
    tone: confirmed ? 'primary' : 'danger',
  })
  if (sure) emit('answer', { question_id: props.question.id, confirmed })
}
function reply() {
  if (props.busy) return
  const value = props.question.method === 'select' ? choice.value : text.value.trim()
  if (value) emit('answer', { question_id: props.question.id, text: value })
}
function onTextareaKeydown(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
    event.preventDefault()
    reply()
  }
}
</script>

<template>
  <section
    class="flex flex-col gap-3 rounded-lg border px-4 py-3.5"
    :class="urgent ? 'animate-rise border-warning/30 bg-warning-bg/60' : 'border-line-strong bg-fill'"
  >
    <div class="flex flex-wrap items-center gap-2">
      <h3 class="flex items-center gap-2 text-sm font-medium text-ink">
        <MessageCircleQuestion :size="16" class="shrink-0 text-warning" aria-hidden="true" />
        {{ t('groups.tasks.question.title') }}
      </h3>
      <span
        v-if="canAnswer && timeoutSeconds && timeoutSeconds > 0"
        class="ml-auto text-xs text-muted tabular"
      >
        {{ t('groups.tasks.question.timeout', { time: formatDuration(timeoutSeconds * 1000) }) }}
      </span>
    </div>
    <p class="text-sm break-words whitespace-pre-wrap text-ink">{{ question.title }}</p>
    <p v-if="question.message" class="text-sm break-words whitespace-pre-wrap text-ink-2">
      {{ question.message }}
    </p>
    <template v-if="canAnswer">
      <div v-if="question.method === 'confirm'" class="flex gap-2">
        <Button variant="primary" size="sm" :loading="busy" @click="decide(true)">
          {{ t('groups.tasks.question.agree') }}
        </Button>
        <Button size="sm" :disabled="busy" @click="decide(false)">
          {{ t('groups.tasks.question.refuse') }}
        </Button>
      </div>
      <template v-else-if="question.method === 'select'">
        <RadioGroup v-model="choice" :options="options" />
        <Button
          variant="primary"
          size="sm"
          class="self-start"
          :disabled="choice === undefined"
          :loading="busy"
          @click="reply"
        >
          {{ t('groups.tasks.question.answer') }}
        </Button>
      </template>
      <template v-else>
        <Textarea
          v-model="text"
          :rows="2"
          :max-rows="10"
          :placeholder="t('groups.tasks.question.placeholder')"
          @keydown="onTextareaKeydown"
        />
        <Button
          variant="primary"
          size="sm"
          class="self-start"
          :disabled="!text.trim()"
          :loading="busy"
          @click="reply"
        >
          {{ t('groups.tasks.question.answer') }}
          <span v-if="!busy" class="ml-0.5 text-2xs font-medium opacity-75 max-sm:hidden">
            {{ mac ? '⌘↵' : 'Ctrl ↵' }}
          </span>
        </Button>
      </template>
    </template>
    <p v-else-if="disabledReason" class="text-xs text-muted">{{ disabledReason }}</p>
  </section>
</template>
