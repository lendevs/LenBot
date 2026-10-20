<script setup lang="ts">
import { computed, provide, ref } from 'vue'
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

const tabNames: Tab[] = ['providers', 'roles', 'vectors', 'usage']
const tab = computed<Tab>({
  get: () => (tabNames.includes(route.query.tab as Tab) ? (route.query.tab as Tab) : 'providers'),
  set: (value) => void router.replace({ query: { tab: value } }),
})
const tabs = computed(() =>
  tabNames.map((value) => ({
    value,
    label: t(`models.tabs.${value}`),
    count: form.problems.value.filter((item) => item.tab === value).length || undefined,
  })),
)
const limitsDirty = ref(false)
useUnsavedChanges(
  computed(() => form.dirty.value || limitsDirty.value),
  { keep: ['tab', 'item'] },
)
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <Tabs v-model="tab" :items="tabs" :label="t('models.title')" />
    <Skeleton v-if="form.settings.isPending.value" :lines="8" />
    <ErrorNote
      v-else-if="form.settings.isError.value"
      :title="t('models.readFailed')"
      :error="form.settings.error.value"
      :retry="form.settings.refetch"
    />
    <template v-else-if="form.draft.value && form.settings.data.value">
      <KeepAlive>
        <ProvidersTab v-if="tab === 'providers'" />
        <RolesTab v-else-if="tab === 'roles'" />
        <VectorsTab v-else-if="tab === 'vectors'" />
        <UsageTab v-else :snapshot="form.settings.data.value" @dirty="(value) => (limitsDirty = value)" />
      </KeepAlive>
      <SaveBar
        v-if="tab !== 'usage'"
        :dirty="form.dirty.value"
        :saving="form.busy.value"
        :error="form.saveError.value"
        :invalid="form.problems.value.length > 0"
        @save="form.save()"
        @discard="form.adopt()"
      />
    </template>
  </div>
</template>
