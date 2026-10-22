<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpRight } from '@lucide/vue'
import Avatar from '../../../ui/Avatar.vue'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import FormSection from '../../../ui/FormSection.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Switch from '../../../ui/Switch.vue'
import { useForm } from './form'

const props = defineProps<{ scene: string }>()

const { t } = useI18n()
const form = useForm()
/** Plugins the host loads; a group can only turn on those. Ones already on here stay listed. */
const items = computed(() => {
  const snapshot = form.plugins.data
  if (!snapshot) return []
  const loaded = Object.keys(snapshot.saved.plugins).filter((name) => !snapshot.saved.disabled.includes(name))
  const names = [...new Set([...loaded, ...(snapshot.scenes[props.scene]?.saved ?? [])])].sort()
  return names.map((name) => {
    const running = snapshot.running.plugins.find((item) => item.name === name)
    const manifest = snapshot.available[name]?.length === 1 ? snapshot.available[name][0] : undefined
    return {
      name,
      description: running?.description ?? manifest?.description ?? '',
      status: running?.status ?? null,
      loaded: loaded.includes(name),
    }
  })
})
function toggle(name: string, on: boolean) {
  const list = form.draft.plugins.filter((item) => item !== name)
  form.draft.plugins = on ? [...list, name] : list
}
</script>

<template>
  <FormSection :title="t('groups.settings.plugins.section')" :columns="1">
    <template #actions>
      <Button size="sm" variant="ghost" :icon-right="ArrowUpRight" :to="{ name: 'host-plugins' }">
        {{ t('groups.settings.plugins.manage') }}
      </Button>
    </template>
    <Skeleton v-if="form.plugins.isPending" :lines="2" />
    <ErrorNote
      v-else-if="form.plugins.isError"
      :title="t('groups.settings.plugins.readFailed')"
      :error="form.plugins.error"
      :retry="form.plugins.refetch"
    />
    <p v-else-if="!items.length" class="text-sm text-muted">{{ t('groups.settings.plugins.empty') }}</p>
    <ul v-else class="flex flex-col divide-y divide-line">
      <li v-for="item in items" :key="item.name" class="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
        <span class="flex" aria-hidden="true"><Avatar :name="item.name" shape="square" :size="32" /></span>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <strong class="text-sm font-medium text-ink">{{ item.name }}</strong>
            <Badge v-if="!item.loaded" tone="warning">{{ t('groups.settings.plugins.notLoaded') }}</Badge>
            <Badge v-else-if="item.status === 'failed'" tone="error">
              {{ t('groups.settings.plugins.failed') }}
            </Badge>
          </div>
          <p v-if="item.description" class="truncate text-xs text-muted" :title="item.description">
            {{ item.description }}
          </p>
        </div>
        <Switch
          :model-value="form.draft.plugins.includes(item.name)"
          :aria-label="item.name"
          @update:model-value="(value: boolean) => toggle(item.name, value)"
        />
      </li>
    </ul>
  </FormSection>
</template>
