<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TaskEventPreview } from '../../../api/tasks'
import Button from '../../../ui/Button.vue'
import EventRow from './EventRow.vue'

defineProps<{
  scene: string
  taskId: number
  events: TaskEventPreview[]
  timeZone: string
  hasMore: boolean
  loadingMore: boolean
}>()
const emit = defineEmits<{ more: [] }>()

const { t } = useI18n()
const open = ref(new Set<number>())
function toggle(id: number) {
  const next = new Set(open.value)
  if (!next.delete(id)) next.add(id)
  open.value = next
}
</script>

<template>
  <section class="flex flex-col gap-2">
    <h3 class="text-sm font-medium text-ink">{{ t('groups.tasks.events.title') }}</h3>
    <p v-if="!events.length" class="text-sm text-muted">{{ t('groups.tasks.events.empty') }}</p>
    <ol v-else class="flex list-none flex-col divide-y divide-line">
      <EventRow
        v-for="event in events"
        :key="event.id"
        :scene="scene"
        :task-id="taskId"
        :event="event"
        :time-zone="timeZone"
        :open="open.has(event.id)"
        @toggle="toggle(event.id)"
      />
    </ol>
    <Button
      v-if="hasMore"
      size="sm"
      variant="ghost"
      class="self-start"
      :loading="loadingMore"
      @click="emit('more')"
    >
      {{ t('groups.tasks.more') }}
    </Button>
  </section>
</template>
