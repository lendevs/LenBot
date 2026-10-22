<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import { confirm } from '../../../ui/confirm'
import ProactiveView from './ProactiveView.vue'
import SchedulesView from './SchedulesView.vue'
import SpaceView from './SpaceView.vue'
import TaskBoard from './TaskBoard.vue'

const props = defineProps<{ scene: string; timeZone: string }>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

type View = 'tasks' | 'schedules' | 'proactive' | 'resources'
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const group = computed(() => props.scene.split(':', 3)[1] === 'group')
const views = computed(() =>
  (['tasks', 'schedules', ...(group.value ? ['proactive'] : []), 'resources'] as View[]).map((value) => ({
    value,
    label: t(`groups.tasks.views.${value}`),
  })),
)
// `tab` is the address the old task page and home page links use.
const view = computed<View>(() => {
  const value = route.query.tab
  return views.value.some((item) => item.value === value) ? (value as View) : 'tasks'
})

const dirty = reactive<Record<string, boolean>>({})
watch(
  () => Object.values(dirty).some(Boolean),
  (value) => emit('dirty', value),
  { immediate: true },
)
const selected = computed({
  get: () => view.value,
  set: (value: View) => void switchTo(value),
})
async function switchTo(value: View) {
  if (value === view.value) return
  if (
    dirty[view.value] &&
    !(await confirm({ title: t('common.unsaved'), confirmLabel: t('common.discard') }))
  )
    return
  dirty[view.value] = false
  void router.replace({ query: value === 'tasks' ? {} : { tab: value } })
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <SegmentedControl
      v-model="selected"
      :options="views"
      :label="t('groups.tabs.tasks')"
      class="self-start"
    />
    <TaskBoard
      v-if="view === 'tasks'"
      :scene="scene"
      :time-zone="timeZone"
      @dirty="(value: boolean) => (dirty.tasks = value)"
    />
    <SchedulesView
      v-else-if="view === 'schedules'"
      :scene="scene"
      @dirty="(value: boolean) => (dirty.schedules = value)"
    />
    <ProactiveView v-else-if="view === 'proactive'" :scene="scene" />
    <SpaceView
      v-else
      :scene="scene"
      :time-zone="timeZone"
      @dirty="(value: boolean) => (dirty.resources = value)"
    />
  </div>
</template>
