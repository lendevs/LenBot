<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, ChevronDown, Search } from '@lucide/vue'
import { groupLabel } from '../../../layouts/shell/scenes'
import Avatar from '../../../ui/Avatar.vue'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import Input from '../../../ui/Input.vue'
import Popover from '../../../ui/Popover.vue'
import { useFieldControl } from '../../../ui/field'
import { controlFrame, controlHeight } from '../../../ui/styles'
import { sceneSecondaryId } from '../view'

/** One group (`single` / `multiple: false`) or several, from the groups in the saved configuration. */
const model = defineModel<string | string[] | null>({ required: true })
const props = defineProps<{
  choices: string[]
  enabledScenes?: string[]
  single?: boolean
  multiple?: boolean
  id?: string
  invalid?: boolean
  disabled?: boolean
  onEnablePicked?: (scenes: string[]) => void | Promise<void>
  enablingPicked?: boolean
}>()

const { t } = useI18n()
const field = useFieldControl(props)
const isSingle = computed(() => Boolean(props.single) || props.multiple === false)
const open = ref(false)
const search = ref('')
watch(open, (value) => {
  if (!value) search.value = ''
})
const picked = computed<string[]>(() =>
  isSingle.value ? (model.value ? [model.value as string] : []) : ((model.value as string[] | null) ?? []),
)
const enabledSet = computed(() => (props.enabledScenes ? new Set(props.enabledScenes) : null))
const inactivePicked = computed(() =>
  enabledSet.value ? picked.value.filter((scene) => !enabledSet.value!.has(scene)) : [],
)
const enableableInactive = computed(() =>
  inactivePicked.value.filter((scene) => props.choices.includes(scene)),
)
// A saved group that is no longer configured or supported stays visible so it can be removed.
const all = computed(() => [
  ...props.choices,
  ...picked.value.filter((scene) => !props.choices.includes(scene)),
])
const shown = computed(() => {
  const words = search.value.trim().toLowerCase()
  return words
    ? all.value.filter((scene) => `${groupLabel(scene)} ${scene}`.toLowerCase().includes(words))
    : all.value
})
const summary = computed(() => {
  const names = picked.value.map(groupLabel)
  return names.length > 2
    ? t('plugins.form.pickedMany', {
        names: names.slice(0, 2).join(t('personas.separator')),
        n: names.length,
      })
    : names.join(t('personas.separator'))
})
function toggle(scene: string) {
  if (isSingle.value) {
    model.value = scene
    open.value = false
  } else {
    model.value = picked.value.includes(scene)
      ? picked.value.filter((item) => item !== scene)
      : [...picked.value, scene]
  }
}
const pickAll = () => (model.value = [...new Set([...picked.value, ...shown.value])])
const clear = () => (model.value = isSingle.value ? null : [])
</script>

<template>
  <div class="flex min-w-0 flex-col gap-1.5">
    <Popover v-model:open="open" width="w-80">
      <template #trigger>
        <button
          :id="field.id.value"
          type="button"
          :disabled="field.disabled.value"
          :class="[controlFrame, controlHeight.md, 'cursor-pointer text-left disabled:cursor-not-allowed']"
          :data-invalid="field.invalid.value || undefined"
          :data-disabled="field.disabled.value || undefined"
          :aria-describedby="field.describedBy.value"
          :aria-expanded="open"
          aria-haspopup="listbox"
        >
          <span v-if="picked.length" class="flex shrink-0" aria-hidden="true">
            <span
              v-for="scene in picked.slice(0, 4)"
              :key="scene"
              class="inline-flex rounded-sm ring-2 ring-surface not-first:-ml-1"
            >
              <Avatar :name="groupLabel(scene)" shape="square" :size="20" />
            </span>
          </span>
          <span class="min-w-0 flex-1 truncate text-sm" :class="picked.length ? 'text-ink' : 'text-subtle'">
            {{
              picked.length ? summary : isSingle ? t('plugins.form.pickOne') : t('plugins.form.pickGroups')
            }}
          </span>
          <ChevronDown
            :size="16"
            class="shrink-0 text-subtle transition-transform"
            :class="open && 'rotate-180'"
            aria-hidden="true"
          />
        </button>
      </template>
      <div class="-m-2 flex flex-col gap-2">
        <Input
          v-if="all.length > 6"
          v-model="search"
          type="search"
          size="sm"
          :icon="Search"
          :placeholder="t('plugins.form.searchGroups')"
          :aria-label="t('plugins.form.searchGroups')"
        />
        <div v-if="!isSingle" class="flex items-center gap-1 pl-2">
          <span class="mr-auto text-xs text-muted tabular">
            {{ t('plugins.form.pickedCount', { n: picked.length, total: all.length }) }}
          </span>
          <Button size="sm" variant="ghost" :disabled="!shown.length" @click="pickAll">
            {{ t('plugins.form.all') }}
          </Button>
          <Button size="sm" variant="ghost" :disabled="!picked.length" @click="clear">
            {{ t('plugins.form.clear') }}
          </Button>
        </div>
        <ul
          class="flex max-h-72 list-none flex-col overflow-y-auto scrollbar-thin"
          role="listbox"
          :aria-multiselectable="!isSingle"
        >
          <li v-for="scene in shown" :key="scene">
            <button
              type="button"
              role="option"
              :aria-selected="picked.includes(scene)"
              class="flex w-full cursor-pointer items-center gap-2.5 rounded-sm px-2 py-1.5 text-left hover:bg-hover focus-visible:focus-ring"
              @click="toggle(scene)"
            >
              <Avatar :name="groupLabel(scene)" shape="square" :size="24" />
              <span class="min-w-0 flex-1">
                <span
                  class="block truncate text-sm text-ink"
                  :class="!choices.includes(scene) && 'line-through'"
                >
                  {{ groupLabel(scene) }}
                </span>
                <span
                  v-if="sceneSecondaryId(scene)"
                  class="block truncate font-mono text-xs text-muted tabular"
                >
                  {{ sceneSecondaryId(scene) }}
                </span>
              </span>
              <Badge
                v-if="enabledSet && !enabledSet.has(scene)"
                :tone="picked.includes(scene) ? 'warning' : 'neutral'"
              >
                {{ t('plugins.form.sceneNotEnabled') }}
              </Badge>
              <span
                class="flex size-4.5 shrink-0 items-center justify-center rounded-sm border"
                :class="
                  picked.includes(scene) ? 'border-primary bg-primary text-on-primary' : 'border-line-strong'
                "
                aria-hidden="true"
              >
                <Check v-if="picked.includes(scene)" :size="12" />
              </span>
            </button>
          </li>
          <li v-if="!shown.length" class="px-2 py-3 text-sm text-muted">
            {{ all.length ? t('common.noResults') : t('plugins.form.noGroups') }}
          </li>
        </ul>
      </div>
    </Popover>
    <p v-if="inactivePicked.length" class="flex flex-wrap items-center gap-1.5 text-xs text-warning">
      <Badge tone="warning" dot>{{ t('plugins.form.sceneNotEnabled') }}</Badge>
      <span>
        {{
          t('plugins.form.sceneNotEnabledHint', {
            names: inactivePicked.map(groupLabel).join(t('personas.separator')),
          })
        }}
      </span>
      <Button
        v-if="onEnablePicked && enableableInactive.length"
        size="sm"
        variant="ghost"
        :loading="enablingPicked"
        :disabled="enablingPicked || field.disabled.value"
        @click="onEnablePicked(enableableInactive)"
      >
        {{ t('plugins.form.enablePickedScenes') }}
      </Button>
    </p>
  </div>
</template>
