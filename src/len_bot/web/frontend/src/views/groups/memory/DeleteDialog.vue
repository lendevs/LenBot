<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation } from '@tanstack/vue-query'
import { Search } from '@lucide/vue'
import { memoryApi, type SourcePage, type SourcePreview } from '../../../api/memory'
import Button from '../../../ui/Button.vue'
import Checkbox from '../../../ui/Checkbox.vue'
import Dialog from '../../../ui/Dialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import RadioGroup from '../../../ui/RadioGroup.vue'
import { toast } from '../../../ui/toast'

const props = defineProps<{ scene: string; path: string; canDelete: boolean; canForget: boolean }>()
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ removed: [] }>()

const LIMIT = 500
const { t } = useI18n()
const mode = ref<'delete' | 'forget'>('delete')
const reason = ref('')
const modes = computed(() =>
  (['delete', 'forget'] as const).map((value) => ({ value, label: t(`groups.memory.remove.modes.${value}`) })),
)
watch(open, (value) => {
  if (!value) return
  mode.value = props.canDelete ? 'delete' : 'forget'
  reason.value = ''
  text.value = ''
  who.value = ''
  rows.value = []
  page.value = null
  chosen.value = new Map()
})

/** Chat messages to skip in later memory ingestion, so the forgotten content is not learned again. */
const text = ref('')
const who = ref('')
const rows = ref<SourcePreview[]>([])
const page = ref<SourcePage | null>(null)
const chosen = ref(new Map<number, SourcePreview>())
const asked = ref<{ query?: string; who?: string }>({})
const finding = ref(false)
const findError = ref<unknown>(null)
async function find(more = false) {
  if (!more) asked.value = { query: text.value.trim() || undefined, who: who.value.trim() || undefined }
  finding.value = true
  findError.value = null
  try {
    const result = await memoryApi.sources(props.scene, {
      ...asked.value,
      ...(more && page.value ? { offset: page.value.next_offset ?? 0, snapshot: page.value.snapshot } : {}),
    })
    rows.value = more ? [...rows.value, ...result.previews] : result.previews
    page.value = result
  } catch (error) {
    findError.value = error
  } finally {
    finding.value = false
  }
}
function toggle(item: SourcePreview, on: boolean | 'indeterminate') {
  const next = new Map(chosen.value)
  if (on === true) next.set(item.record, item)
  else next.delete(item.record)
  chosen.value = next
}

const remove = useMutation({
  mutationFn: () =>
    memoryApi.remove({
      scene: props.scene,
      path: props.path,
      reason: reason.value.trim(),
      forget: mode.value === 'forget',
      exclude_records: mode.value === 'forget' ? [...chosen.value.keys()] : null,
    }),
  onSuccess: () => {
    toast.success(t(mode.value === 'forget' ? 'groups.memory.remove.forgotten' : 'groups.memory.remove.deleted'))
    emit('removed')
  },
})
const actionLabel = computed(() =>
  mode.value === 'delete'
    ? t('common.delete')
    : chosen.value.size
      ? t('groups.memory.remove.forgetSkip', { n: chosen.value.size })
      : t('groups.memory.remove.forget'),
)
</script>

<template>
  <Dialog v-model:open="open" :title="t('groups.memory.remove.title', { path })" size="lg" :busy="remove.isPending.value">
    <div class="flex flex-col gap-4">
      <RadioGroup v-if="canDelete && canForget" v-model="mode" :options="modes" />
      <p class="text-sm text-ink-2">{{ t(`groups.memory.remove.explain.${mode}`) }}</p>
      <Field :label="t('groups.memory.remove.reason')">
        <Input v-model="reason" />
      </Field>
      <section v-if="mode === 'forget'" class="flex flex-col gap-3 border-t border-line pt-4">
        <h4 class="text-sm font-semibold text-ink">{{ t('groups.memory.remove.sources') }}</h4>
        <form class="grid gap-2 sm:grid-cols-[minmax(0,1fr)_180px_auto]" @submit.prevent="find()">
          <Input v-model="text" :aria-label="t('groups.memory.remove.text')" :placeholder="t('groups.memory.remove.text')" />
          <Input v-model="who" :aria-label="t('groups.memory.remove.who')" placeholder="onebot:10001" mono />
          <Button type="submit" :icon="Search" :loading="finding">{{ t('common.search') }}</Button>
        </form>
        <ErrorNote v-if="findError" :title="t('groups.memory.readFailed')" :error="findError" />
        <p v-if="page && !rows.length" class="text-sm text-muted">{{ t('common.noResults') }}</p>
        <ul v-if="rows.length" class="flex max-h-80 list-none flex-col divide-y divide-line overflow-y-auto scrollbar-thin">
          <li v-for="item in rows" :key="item.record">
            <label class="flex cursor-pointer items-start gap-2.5 py-2" :class="item.excluded && 'cursor-default opacity-60'">
              <span class="pt-0.5">
                <Checkbox
                  :model-value="item.excluded || chosen.has(item.record)"
                  :disabled="item.excluded || (!chosen.has(item.record) && chosen.size >= LIMIT)"
                  @update:model-value="(on) => toggle(item, on)"
                />
              </span>
              <span class="min-w-0 flex-1 font-mono text-xs leading-5 break-words whitespace-pre-wrap text-ink-2">
                <span v-if="item.excluded" class="mr-1 font-sans text-subtle">{{ t('groups.memory.remove.skipped') }}</span>{{ item.text }}
              </span>
            </label>
          </li>
        </ul>
        <Button v-if="page?.next_offset != null" size="sm" variant="ghost" :loading="finding" class="self-center" @click="find(true)">
          {{ t('groups.memory.more') }}
        </Button>
        <p v-if="chosen.size" class="text-xs text-muted">
          {{ t('groups.memory.remove.chosen', { n: chosen.size }) }}<template v-if="chosen.size >= LIMIT">{{ t('groups.memory.remove.limit') }}</template>
        </p>
      </section>
      <ErrorNote v-if="remove.isError.value" :title="t('groups.memory.remove.failed')" :error="remove.error.value" />
    </div>
    <template #footer>
      <Button variant="ghost" :disabled="remove.isPending.value" @click="open = false">{{ t('common.cancel') }}</Button>
      <Button variant="danger" :loading="remove.isPending.value" :disabled="!reason.trim()" @click="remove.mutate()">
        {{ actionLabel }}
      </Button>
    </template>
  </Dialog>
</template>
