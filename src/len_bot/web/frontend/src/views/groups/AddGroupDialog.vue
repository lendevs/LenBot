<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { Check } from '@lucide/vue'
import { hostApi } from '../../api/host'
import { keys } from '../../api/query'
import { sceneTitles } from '../../api/scenes'
import { readHostState, readSceneTitles } from '../../api/hostStore'
import { formatNumber } from '../../i18n/format'
import Avatar from '../../ui/Avatar.vue'
import Button from '../../ui/Button.vue'
import Dialog from '../../ui/Dialog.vue'
import EmptyState from '../../ui/EmptyState.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import Input from '../../ui/Input.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import Select from '../../ui/Select.vue'
import Skeleton from '../../ui/Skeleton.vue'
import { toast } from '../../ui/toast'

const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ added: [scene: string] }>()

const { t } = useI18n()
const client = useQueryClient()
const picked = ref<string | null>(null)
const kind = ref<'group' | 'private'>('group')
const number = ref('')
const persona = ref<string>()

const available = useQuery({
  queryKey: keys.host.availableScenes(),
  queryFn: ({ signal }) => hostApi.availableScenes(signal),
  enabled: open,
  staleTime: 0,
})
const personas = useQuery({
  queryKey: keys.personas.all(),
  queryFn: ({ signal }) => hostApi.personas(signal),
  enabled: open,
})
const personaOptions = computed(() =>
  (personas.data.value?.roles ?? [])
    .filter((role) => !role.error)
    .map((role) => ({ value: role.config_path, label: role.name || role.key })),
)
watch(personaOptions, (options) => {
  if (!persona.value && options.length === 1) persona.value = options[0].value
})

const manual = computed(() => (number.value.trim() ? `onebot:${kind.value}:${number.value.trim()}` : ''))
const target = computed(() => picked.value ?? manual.value)
watch(number, (value) => {
  if (value.trim()) picked.value = null
})
function pick(scene: string) {
  picked.value = picked.value === scene ? null : scene
  if (picked.value) number.value = ''
}

const add = useMutation({
  mutationFn: () => hostApi.addScene(target.value, persona.value ?? ''),
  onSuccess: async () => {
    const scene = target.value
    const item = available.data.value?.items.find((entry) => entry.scene === scene)
    if (item?.name) (sceneTitles as Record<string, string>)[scene] = item.name
    await readHostState()
    void readSceneTitles()
    void client.invalidateQueries({ queryKey: keys.host.availableScenes() })
    toast.success(t('groups.join.done', { name: item?.name || scene.split(':').slice(2).join(':') }))
    open.value = false
    emit('added', scene)
  },
})
watch(open, (value) => {
  if (!value) return
  add.reset()
  picked.value = null
  number.value = ''
})
</script>

<template>
  <Dialog v-model:open="open" :title="t('groups.join.title')" :busy="add.isPending.value">
    <div class="flex flex-col gap-5">
      <section class="flex flex-col gap-2">
        <h3 class="text-sm font-medium text-ink-2">
          {{ t('groups.join.joined') }}
        </h3>
        <Skeleton v-if="available.isPending.value" :lines="3" />
        <ErrorNote
          v-else-if="available.isError.value"
          :title="t('groups.join.readFailed')"
          :error="available.error.value"
          :retry="available.refetch"
        />
        <EmptyState v-else-if="!available.data.value?.items.length" :title="t('groups.join.none')" compact />
        <div v-else class="-mx-1 flex max-h-64 flex-col gap-0.5 overflow-y-auto px-1 scrollbar-thin">
          <button
            v-for="item in available.data.value.items"
            :key="item.scene"
            type="button"
            class="flex w-full cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-hover focus-visible:focus-ring aria-pressed:bg-selected"
            :aria-pressed="picked === item.scene"
            @click="pick(item.scene)"
          >
            <Avatar :name="item.name || item.scene.split(':').pop() || '?'" shape="square" :size="30" />
            <span class="grid min-w-0 flex-1 leading-snug">
              <span class="truncate text-base">
                {{ item.name || item.scene.split(':').slice(2).join(':') }}
              </span>
              <span class="truncate text-xs text-muted tabular">
                {{ item.scene.split(':').slice(2).join(':') }}
                <template v-if="item.members">
                  · {{ t('groups.members', { n: formatNumber(item.members) }) }}
                </template>
              </span>
            </span>
            <Check v-if="picked === item.scene" :size="16" class="shrink-0 text-primary" aria-hidden="true" />
          </button>
        </div>
      </section>

      <section class="flex flex-col gap-2">
        <h3 class="text-sm font-medium text-ink-2">{{ t('groups.join.manual') }}</h3>
        <div class="flex flex-wrap items-center gap-2">
          <SegmentedControl
            v-model="kind"
            :options="[
              { value: 'group', label: t('groups.join.kinds.group') },
              { value: 'private', label: t('groups.join.kinds.private') },
            ]"
            :label="t('groups.join.manual')"
          />
          <Input
            v-model="number"
            inputmode="numeric"
            :placeholder="kind === 'group' ? t('groups.join.number') : t('groups.join.account')"
            :aria-label="kind === 'group' ? t('groups.join.number') : t('groups.join.account')"
            class="min-w-40 flex-1"
            mono
          />
        </div>
      </section>

      <Field :label="t('groups.join.persona')" required>
        <Select v-model="persona" :options="personaOptions" :disabled="personas.isPending.value" />
      </Field>
      <ErrorNote v-if="personas.isError.value" :error="personas.error.value" :retry="personas.refetch" />
      <ErrorNote v-if="add.isError.value" :title="t('groups.join.failed')" :error="add.error.value" />
    </div>
    <template #footer>
      <Button variant="ghost" :disabled="add.isPending.value" @click="open = false">
        {{ t('common.cancel') }}
      </Button>
      <Button
        variant="primary"
        :loading="add.isPending.value"
        :disabled="!target || !persona"
        @click="add.mutate()"
      >
        {{ t('groups.join.submit') }}
      </Button>
    </template>
  </Dialog>
</template>
