<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { Download, Sparkles } from '@lucide/vue'
import { keys } from '../../../api/query'
import { tasksApi, type SkillInfo, type TaskDetail } from '../../../api/tasks'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import SkillDialog from './SkillDialog.vue'
import { finished } from './labels'

const props = defineProps<{ scene: string; task: TaskDetail['task']; configured: boolean }>()

const { t } = useI18n()
/** The session file and the task's own skills are read only once the task has stopped. */
const stopped = computed(() => props.configured && finished(props.task.status) && props.task.container === null)
const skills = useQuery({
  queryKey: computed(() => keys.tasks.skills(props.scene, props.task.id)),
  queryFn: ({ signal }) => tasksApi.skills(props.scene, props.task.id, signal),
  enabled: stopped,
})
const inspected = ref<SkillInfo | null>(null)
const inspecting = computed({
  get: () => inspected.value !== null,
  set: (value: boolean) => {
    if (!value) inspected.value = null
  },
})
</script>

<template>
  <section class="flex flex-col gap-3 border-t border-line pt-4">
    <h3 class="text-sm font-medium text-ink">{{ t('groups.tasks.extra.title') }}</h3>
    <div class="flex flex-wrap gap-2">
      <Button v-if="stopped" size="sm" variant="ghost" :icon="Download" :href="tasksApi.sessionUrl(scene, task.id)">
        {{ t('groups.tasks.extra.session') }}
      </Button>
      <Button size="sm" variant="ghost" :icon="Download" :href="tasksApi.exportUrl(scene, task.id)">
        {{ t('groups.tasks.extra.export') }}
      </Button>
    </div>
    <template v-if="stopped">
      <h4 class="text-sm text-ink-2">{{ t('groups.tasks.extra.skills') }}</h4>
      <Skeleton v-if="skills.isPending.value" :lines="2" />
      <ErrorNote
        v-else-if="skills.isError.value"
        :title="t('groups.tasks.extra.readSkills')"
        :error="skills.error.value"
        :retry="skills.refetch"
      />
      <p v-else-if="!skills.data.value?.items.length" class="text-sm text-muted">{{ t('groups.tasks.extra.noSkills') }}</p>
      <ul v-else class="flex list-none flex-col divide-y divide-line rounded-lg border border-line">
        <li v-for="item in skills.data.value.items" :key="item.name" class="flex items-center gap-2.5 px-3 py-2">
          <Sparkles :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm text-ink">{{ item.name }}</p>
            <p v-if="item.description" class="line-clamp-2 text-xs text-muted">{{ item.description }}</p>
          </div>
          <Button size="sm" variant="ghost" @click="inspected = item">{{ t('groups.tasks.extra.view') }}</Button>
        </li>
      </ul>
    </template>
    <SkillDialog
      v-if="inspected"
      v-model:open="inspecting"
      :scene="scene"
      :task-id="task.id"
      :name="inspected.name"
      @moved="inspected = null"
    />
  </section>
</template>
