<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { keys } from '../../../api/query'
import { tasksApi } from '../../../api/tasks'
import { groupLabel } from '../../../layouts/shell/scenes'
import Button from '../../../ui/Button.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import Dialog from '../../../ui/Dialog.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { confirm } from '../../../ui/confirm'
import { toast } from '../../../ui/toast'

const props = defineProps<{ scene: string; taskId: number; name: string }>()
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ moved: [] }>()

const { t } = useI18n()
const client = useQueryClient()
const listing = useQuery({
  queryKey: computed(() => keys.tasks.skillFiles(props.scene, props.taskId, props.name)),
  queryFn: ({ signal }) => tasksApi.skillFiles(props.scene, props.taskId, props.name, signal),
})

/** The open file, read in pages. */
const path = ref<string | null>(null)
const text = ref('')
const next = ref<number | null>(null)
const read = useMutation({
  mutationFn: ({ file, offset }: { file: string; offset: number }) =>
    tasksApi.skillText(props.scene, props.taskId, props.name, file, offset),
  onSuccess: (page, { file, offset }) => {
    path.value = file
    text.value = offset ? text.value + page.content : page.content
    next.value = page.next_offset
  },
})
watch(
  () => listing.data.value,
  (value) => {
    if (value && path.value === null && value.files.some((file) => file.path === 'SKILL.md'))
      read.mutate({ file: 'SKILL.md', offset: 0 })
  },
  { immediate: true },
)

const move = useMutation({
  mutationFn: (target: 'scene' | 'shared') => tasksApi.moveSkill(props.scene, props.taskId, props.name, target),
  onSuccess: () => {
    toast.success(t('groups.tasks.skill.moved'))
    client.removeQueries({ queryKey: keys.tasks.skillFiles(props.scene, props.taskId, props.name) })
    void client.invalidateQueries({ queryKey: keys.tasks.skills(props.scene, props.taskId) })
    emit('moved')
  },
})
async function moveTo(target: 'scene' | 'shared') {
  const place = t(`groups.tasks.skill.places.${target}`)
  const sure = await confirm({
    title: t('groups.tasks.skill.moveTitle', { name: props.name, place }),
    message: t('groups.tasks.skill.moveText'),
    confirmLabel: t('groups.tasks.skill.move'),
    tone: 'primary',
  })
  if (sure) move.mutate(target)
}
</script>

<template>
  <Dialog v-model:open="open" :title="name" size="lg" :busy="move.isPending.value">
    <Skeleton v-if="listing.isPending.value" :lines="6" />
    <ErrorNote
      v-else-if="listing.isError.value"
      :title="t('groups.tasks.skill.readFailed')"
      :error="listing.error.value"
      :retry="listing.refetch"
    />
    <div v-else-if="listing.data.value" class="flex min-w-0 flex-col gap-3">
      <p v-if="listing.data.value.skill.description" class="text-sm text-ink-2">{{ listing.data.value.skill.description }}</p>
      <p v-if="listing.data.value.used_by_running.length" class="text-xs text-muted">
        {{ t('groups.tasks.skill.usedBy', { groups: listing.data.value.used_by_running.map((item) => groupLabel(item)).join('、') }) }}
      </p>
      <div class="flex flex-wrap gap-1.5">
        <Button
          v-for="file in listing.data.value.files"
          :key="file.path"
          size="sm"
          :variant="file.path === path ? 'secondary' : 'ghost'"
          class="font-mono"
          :aria-pressed="file.path === path"
          @click="read.mutate({ file: file.path, offset: 0 })"
        >
          {{ file.path }}
        </Button>
      </div>
      <ErrorNote v-if="read.isError.value" :title="t('groups.tasks.skill.readFile')" :error="read.error.value" />
      <CodeBlock v-if="path" :code="text || t('groups.tasks.skill.emptyFile')" :label="path" wrap :max-lines="30" />
      <Button
        v-if="next !== null && path"
        size="sm"
        variant="ghost"
        class="self-start"
        :loading="read.isPending.value"
        @click="read.mutate({ file: path, offset: next })"
      >
        {{ t('groups.tasks.skill.continue') }}
      </Button>
      <ErrorNote v-if="move.isError.value" :title="t('groups.tasks.actionFailed')" :error="move.error.value" />
    </div>
    <template #footer>
      <Button :disabled="!listing.data.value" :loading="move.isPending.value && move.variables.value === 'scene'" @click="moveTo('scene')">
        {{ t('groups.tasks.skill.moveScene') }}
      </Button>
      <Button
        variant="primary"
        :disabled="!listing.data.value"
        :loading="move.isPending.value && move.variables.value === 'shared'"
        @click="moveTo('shared')"
      >
        {{ t('groups.tasks.skill.moveShared') }}
      </Button>
    </template>
  </Dialog>
</template>
