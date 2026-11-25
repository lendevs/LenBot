<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, provide, ref, toRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import ErrorNote from '../../../ui/ErrorNote.vue'
import SaveBar from '../../../ui/SaveBar.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import { toast } from '../../../ui/toast'
import FocusSection from './FocusSection.vue'
import ParticipationSection from './ParticipationSection.vue'
import PermissionsSection from './PermissionsSection.vue'
import PersonaSection from './PersonaSection.vue'
import PluginsSection from './PluginsSection.vue'
import ProactiveSection from './ProactiveSection.vue'
import QuietSection from './QuietSection.vue'
import RemoveSection from './RemoveSection.vue'
import RoleSection from './RoleSection.vue'
import SpeechSection from './SpeechSection.vue'
import TasksSection from './TasksSection.vue'
import { errorSection, formKey, useSettingsForm, type SettingsSectionId } from './form'
import { confirmMemorySwitch } from './memory'

const props = defineProps<{ scene: string; timeZone: string }>()
const emit = defineEmits<{ dirty: [value: boolean] }>()

const { t } = useI18n()
const route = useRoute()
const form = useSettingsForm(toRef(props, 'scene'))
provide(formKey, form)
const group = computed(() => props.scene.split(':')[1] === 'group')
watch(
  () => form.dirty,
  (value) => emit('dirty', value),
  { immediate: true },
)

const sections = computed<SettingsSectionId[]>(() => [
  'role',
  'participation',
  'focus',
  'quiet',
  ...(group.value ? (['speech', 'proactive'] as const) : []),
  'persona',
  'tasks',
  'plugins',
  'permissions',
  'danger',
])

const formEl = ref<HTMLFormElement | null>(null)
const activeSection = ref<SettingsSectionId>('role')

function jumpTo(id: SettingsSectionId) {
  activeSection.value = id
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

let observer: IntersectionObserver | null = null
function observeSections() {
  observer?.disconnect()
  observer = null
  const container = formEl.value
  if (!container) return
  const visible = new Set<SettingsSectionId>()
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const id = entry.target.id as SettingsSectionId
        if (entry.isIntersecting) visible.add(id)
        else visible.delete(id)
      }
      const first = sections.value.find((id) => visible.has(id))
      if (first) activeSection.value = first
    },
    { rootMargin: '-88px 0px -65% 0px', threshold: 0 },
  )
  for (const id of sections.value) {
    const el = document.getElementById(id)
    if (el) observer.observe(el)
  }
}
watch(
  [() => Boolean(form.draft), sections, formEl],
  async ([ready]) => {
    if (!ready) {
      observer?.disconnect()
      return
    }
    await nextTick()
    observeSections()
  },
  { immediate: true },
)
onBeforeUnmount(() => observer?.disconnect())

// Deep-link via `?section=<id>` from other group views.
watch(
  [() => route.query.section, () => Boolean(form.draft)],
  async ([section, ready]) => {
    if (!ready || typeof section !== 'string') return
    if (!sections.value.includes(section as SettingsSectionId)) return
    await nextTick()
    jumpTo(section as SettingsSectionId)
  },
  { immediate: true },
)

const orderedErrorEntries = computed(() => {
  const order = new Map(sections.value.map((id, index) => [id, index]))
  return Object.entries(form.errors).sort(
    ([a], [b]) => (order.get(errorSection(a)) ?? 99) - (order.get(errorSection(b)) ?? 99),
  )
})
const firstErrorEntry = computed(() => orderedErrorEntries.value[0] ?? null)

async function locateError() {
  const first = firstErrorEntry.value
  if (!first) return
  const [key] = first
  if (key.startsWith('attention.declarations.') || key.startsWith('attention.disposition.')) {
    form.expanded.focusDetails = true
  } else if (key.startsWith('attention.')) {
    form.expanded.participationDetails = true
  } else if (
    key.startsWith('permissions.task_identities.') ||
    key.startsWith('permissions.schedule_identities.')
  ) {
    form.expanded.permissionsScoped = true
  }
  await nextTick()
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  const target =
    formEl.value?.querySelector<HTMLElement>('[aria-invalid="true"]') ??
    formEl.value?.querySelector<HTMLElement>('[data-invalid="true"] input, [data-invalid="true"] textarea') ??
    formEl.value?.querySelector<HTMLElement>('[data-invalid="true"]')
  if (target) {
    activeSection.value = errorSection(key)
    target.scrollIntoView({ behavior: 'smooth', block: 'center' })
    target.focus({ preventScroll: true })
  } else {
    jumpTo(errorSection(key))
  }
}

async function save() {
  if (form.invalid) {
    await locateError()
    return
  }
  if (form.memoryChanged && !(await confirmMemorySwitch())) return
  const result = await form.save()
  if (result === 'restart') toast.success(t('groups.settings.savedRestart'))
  else if (result === 'saved') toast.success(t('common.saved'))
}
</script>

<template>
  <div class="min-w-0">
    <Skeleton v-if="form.settings.isPending" :lines="10" class="max-w-3xl" />
    <ErrorNote
      v-else-if="form.settings.isError"
      :title="t('groups.settings.readFailed')"
      :error="form.settings.error"
      :retry="form.settings.refetch"
      class="max-w-3xl"
    />
    <p v-else-if="!form.saved" class="text-sm text-muted">{{ t('groups.settings.removed') }}</p>
    <div
      v-else-if="form.draft"
      class="flex min-w-0 flex-col gap-5 xl:grid xl:max-w-5xl xl:grid-cols-[176px_minmax(0,1fr)] xl:items-start xl:gap-8"
    >
      <nav
        :aria-label="t('groups.settings.nav.label')"
        class="-mx-1 flex items-center gap-1.5 overflow-x-auto px-1 pb-1 scrollbar-none xl:hidden"
      >
        <button
          v-for="id in sections"
          :key="id"
          type="button"
          class="inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium whitespace-nowrap transition-colors focus-visible:focus-ring"
          :class="
            activeSection === id
              ? 'border-primary bg-selected text-ink'
              : 'border-line bg-surface text-muted hover:border-line-strong hover:text-ink'
          "
          :aria-current="activeSection === id ? 'location' : undefined"
          @click="jumpTo(id)"
        >
          <span>{{ t(`groups.settings.nav.${id}`) }}</span>
          <span
            v-if="form.sectionErrors[id] || form.sectionDirty[id]"
            class="size-1.5 shrink-0 rounded-full"
            :class="form.sectionErrors[id] ? 'bg-error' : 'bg-warning'"
            aria-hidden="true"
          />
        </button>
      </nav>

      <nav :aria-label="t('groups.settings.nav.label')" class="sticky top-20 hidden flex-col gap-0.5 xl:flex">
        <button
          v-for="id in sections"
          :key="id"
          type="button"
          class="flex w-full cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors focus-visible:focus-ring"
          :class="
            activeSection === id
              ? 'bg-selected font-medium text-ink'
              : 'text-muted hover:bg-hover hover:text-ink'
          "
          :aria-current="activeSection === id ? 'location' : undefined"
          @click="jumpTo(id)"
        >
          <span class="min-w-0 flex-1 truncate">{{ t(`groups.settings.nav.${id}`) }}</span>
          <span
            v-if="form.sectionErrors[id] || form.sectionDirty[id]"
            class="size-1.5 shrink-0 rounded-full"
            :class="form.sectionErrors[id] ? 'bg-error' : 'bg-warning'"
            aria-hidden="true"
          />
        </button>
      </nav>

      <form ref="formEl" class="flex min-w-0 max-w-3xl flex-col gap-8 pb-8" @submit.prevent="save">
        <RoleSection :scene="scene" />
        <ParticipationSection />
        <FocusSection :scene="scene" />
        <QuietSection />
        <SpeechSection v-if="group" :scene="scene" :time-zone="timeZone" />
        <ProactiveSection v-if="group" />
        <PersonaSection />
        <TasksSection />
        <PluginsSection :scene="scene" />
        <PermissionsSection />
        <RemoveSection :scene="scene" />
        <SaveBar
          :dirty="form.dirty"
          :saving="form.saving"
          :error="form.saveError ?? (form.dirty && form.invalid ? (firstErrorEntry?.[1] ?? null) : null)"
          :raw-error="form.saveError ? form.saveRawError : null"
          :invalid="form.invalid"
          :action-label="form.invalid && !form.saveError ? t('common.locateError') : undefined"
          @save="save"
          @discard="form.adopt"
          @action="locateError"
        />
      </form>
    </div>
  </div>
</template>
