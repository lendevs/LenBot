<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { Shuffle } from '@lucide/vue'
import { personasApi, type PersonaRole } from '../../../api/personas'
import { keys } from '../../../api/query'
import { formatNumber } from '../../../i18n/format'
import { groupLabel } from '../../../layouts/shell/scenes'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import CodeBlock from '../../../ui/CodeBlock.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import Field from '../../../ui/Field.vue'
import Select from '../../../ui/Select.vue'
import Skeleton from '../../../ui/Skeleton.vue'

const props = defineProps<{ role: PersonaRole }>()

const { t } = useI18n()
/** Select options cannot be empty; this stands for the role without any group's settings. */
const NONE = '*'
const scene = ref(props.role.scenes[0] ?? NONE)
watch(
  () => props.role.scenes.join(),
  () => {
    if (scene.value !== NONE && !props.role.scenes.includes(scene.value))
      scene.value = props.role.scenes[0] ?? NONE
  },
)
const options = computed(() => [
  ...props.role.scenes.map((value) => ({ value, label: groupLabel(value) })),
  { value: NONE, label: t('personas.detail.preview.noScene') },
])
const chosen = computed(() => (scene.value === NONE ? null : scene.value))

const preview = useQuery({
  queryKey: computed(() => [...keys.personas.part(props.role.key, 'preview'), chosen.value]),
  queryFn: ({ signal }) => personasApi.preview(props.role.key, chosen.value, signal),
  staleTime: 0,
})
const title = (name: string) =>
  name === 'character'
    ? t('personas.detail.preview.character')
    : t(`personas.detail.files.names.${name.replace('.', '_')}`)
</script>

<template>
  <div class="flex max-w-4xl flex-col gap-6">
    <Field :label="t('personas.detail.preview.scene')">
      <Select v-model="scene" :options="options" class="sm:max-w-xs" />
    </Field>
    <Skeleton v-if="preview.isPending.value" :lines="10" />
    <ErrorNote
      v-else-if="preview.isError.value"
      :title="t('personas.detail.preview.readFailed')"
      :error="preview.error.value"
      :retry="preview.refetch"
    />
    <template v-else-if="preview.data.value">
      <section v-for="section in preview.data.value.sections" :key="section.name" class="flex flex-col gap-2">
        <h3 class="flex flex-wrap items-center gap-2 text-sm font-semibold text-ink">
          {{ title(section.name) }}
          <Badge v-if="section.name === 'character'">
            {{ t('personas.detail.preview.examples', { n: preview.data.value.examples }) }}
          </Badge>
          <Badge v-else :tone="section.own ? 'brand' : 'neutral'">
            {{ section.own ? t('personas.detail.preview.own') : t('personas.detail.preview.framework') }}
          </Badge>
        </h3>
        <CodeBlock :code="section.text" :max-lines="section.name === 'character' ? 40 : 12" />
      </section>
      <section v-if="preview.data.value.styles.length" class="flex flex-col gap-2">
        <h3 class="text-sm font-semibold text-ink">{{ t('personas.detail.preview.styles') }}</h3>
        <ul class="flex list-none flex-wrap gap-2">
          <li v-for="style in preview.data.value.styles" :key="style.name">
            <Badge>
              {{ style.name }} ·
              {{ formatNumber(style.weight, { style: 'percent', maximumFractionDigits: 1 }) }}
            </Badge>
          </li>
        </ul>
        <div class="flex items-center justify-between gap-3">
          <span class="text-sm text-ink-2">{{ t('personas.detail.preview.drawn') }}</span>
          <Button size="sm" variant="ghost" :icon="Shuffle" @click="preview.refetch()">
            {{ t('personas.detail.preview.draw') }}
          </Button>
        </div>
        <CodeBlock v-if="preview.data.value.style" :code="preview.data.value.style" :max-lines="0" />
      </section>
    </template>
  </div>
</template>
