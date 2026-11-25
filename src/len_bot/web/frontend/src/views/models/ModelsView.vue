<script setup lang="ts">
import { computed, nextTick, provide, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useUnsavedChanges } from '../../composables/useUnsavedChanges'
import ErrorNote from '../../ui/ErrorNote.vue'
import SaveBar from '../../ui/SaveBar.vue'
import Skeleton from '../../ui/Skeleton.vue'
import Tabs from '../../ui/Tabs.vue'
import ProvidersTab from './ProvidersTab.vue'
import RolesTab from './RolesTab.vue'
import UsageTab from './UsageTab.vue'
import VectorsTab from './VectorsTab.vue'
import { modelsKey, useModelsForm, type Tab } from './form'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const form = useModelsForm()
provide(modelsKey, form)

const root = ref<HTMLElement>()
const tabNames: Tab[] = ['providers', 'roles', 'vectors', 'usage']
const tab = computed<Tab>({
  get: () => (tabNames.includes(route.query.tab as Tab) ? (route.query.tab as Tab) : 'providers'),
  set: (value) => void router.replace({ query: { tab: value } }),
})
const limitsDirty = ref(false)
const tabs = computed(() =>
  tabNames.map((value) => {
    const count = form.problems.value.filter((item) => item.tab === value).length
    const isDirty = value === 'usage' ? limitsDirty.value : form.tabDirty.value[value]
    return {
      value,
      label: t(`models.tabs.${value}`),
      count: count || undefined,
      dot: count > 0 ? ('error' as const) : isDirty ? ('warning' as const) : undefined,
    }
  }),
)
useUnsavedChanges(
  computed(() => form.dirty.value || limitsDirty.value),
  { keep: ['tab', 'item'] },
)

async function locateProblem() {
  form.triedSave.value = true
  const first = form.problems.value[0]
  if (!first) return
  const switchedTab = tab.value !== first.tab
  if (first.tab === 'providers' && first.provider) {
    if (switchedTab || route.query.item !== first.provider) {
      await router.replace({ query: { tab: 'providers', item: first.provider } })
    }
  } else if (switchedTab) {
    await router.replace({ query: { tab: first.tab } })
  }
  await nextTick()
  const findTarget = () =>
    root.value?.querySelector<HTMLElement>('[data-invalid], [aria-invalid="true"], [data-problem-banner]') ??
    null
  let target = findTarget()
  if (!target && switchedTab) {
    await new Promise((resolve) => setTimeout(resolve, 180))
    await nextTick()
    target = findTarget()
  }
  if (!target) return
  target.scrollIntoView({ behavior: 'smooth', block: 'center' })
  const focusable = target.matches('input, textarea, select, button, a, [tabindex]')
    ? target
    : target.querySelector<HTMLElement>('input, textarea, select, button, a, [tabindex]')
  focusable?.focus({ preventScroll: true })
}
</script>

<template>
  <div ref="root" class="flex min-w-0 flex-col gap-6 pb-2">
    <Tabs v-model="tab" :items="tabs" :label="t('models.title')" />
    <Skeleton v-if="form.settings.isPending.value" :lines="8" />
    <ErrorNote
      v-else-if="form.settings.isError.value"
      :title="t('models.readFailed')"
      :error="form.settings.error.value"
      :retry="form.settings.refetch"
    />
    <template v-else-if="form.draft.value && form.settings.data.value">
      <Transition name="ui-tab" mode="out-in">
        <KeepAlive>
          <ProvidersTab v-if="tab === 'providers'" key="providers" />
          <RolesTab v-else-if="tab === 'roles'" key="roles" />
          <VectorsTab v-else-if="tab === 'vectors'" key="vectors" />
          <UsageTab
            v-else
            key="usage"
            :snapshot="form.settings.data.value"
            @dirty="(value) => (limitsDirty = value)"
          />
        </KeepAlive>
      </Transition>
      <SaveBar
        v-if="tab !== 'usage'"
        :dirty="form.dirty.value"
        :saving="form.busy.value"
        :error="form.saveError.value"
        :raw-error="form.saveRawError.value"
        :invalid="form.problems.value.length > 0"
        :action-label="form.hasProblem.value ? t('common.locateError') : undefined"
        @save="form.save()"
        @discard="form.adopt()"
        @action="locateProblem"
      />
    </template>
  </div>
</template>
