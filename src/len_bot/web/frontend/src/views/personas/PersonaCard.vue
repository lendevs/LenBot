<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Copy, Download, MoreHorizontal, Trash2, TriangleAlert } from '@lucide/vue'
import { personaAvatar } from '../../api/host'
import { firstSentence, type PersonaRole } from '../../api/personas'
import { groupLabel } from '../../layouts/shell/scenes'
import Avatar from '../../ui/Avatar.vue'
import DropdownMenu, { type MenuEntry } from '../../ui/DropdownMenu.vue'
import IconButton from '../../ui/IconButton.vue'

const props = defineProps<{ role: PersonaRole; busy?: boolean }>()
const emit = defineEmits<{ open: []; copy: []; export: []; remove: [] }>()

const MAX_SCENES = 2
const { t } = useI18n()
const name = computed(() => props.role.name || props.role.key)
const broken = computed(() => Boolean(props.role.error))
const usage = computed(() => {
  const names = props.role.scenes.map(groupLabel)
  if (!names.length) return t('personas.unused')
  return names.length > MAX_SCENES
    ? t('personas.usedMany', {
        names: names.slice(0, MAX_SCENES).join(t('personas.separator')),
        n: names.length,
        more: names.length - MAX_SCENES,
      })
    : t('personas.used', { names: names.join(t('personas.separator')) })
})
const items = computed<MenuEntry[]>(() => [
  { label: t('personas.copy'), icon: Copy, disabled: broken.value, select: () => emit('copy') },
  { label: t('personas.export'), icon: Download, disabled: broken.value, select: () => emit('export') },
  { type: 'separator' },
  {
    label:
      props.role.scenes.length || props.role.running_scenes.length
        ? t('personas.removeInUse')
        : t('common.delete'),
    icon: Trash2,
    danger: true,
    disabled: Boolean(props.role.scenes.length || props.role.running_scenes.length),
    select: () => emit('remove'),
  },
])
</script>

<template>
  <article
    class="group relative flex flex-col gap-3 rounded-lg border border-line bg-surface p-4 shadow-card transition-[border-color,box-shadow] duration-150 hover:border-line-strong hover:shadow-hover"
  >
    <div class="flex items-center gap-3">
      <span class="inline-flex shrink-0 rounded-full ring-1 ring-line">
        <Avatar :name="name" :src="personaAvatar(role)" :size="44" />
      </span>
      <div class="min-w-0 flex-1">
        <!-- The stretched link makes the whole card open the role; the menu sits above it. -->
        <button
          type="button"
          class="block max-w-full cursor-pointer truncate text-left text-base font-semibold after:absolute after:inset-0 after:rounded-lg focus-visible:outline-none focus-visible:after:focus-ring"
          :class="role.scenes.length ? 'text-ink' : 'text-ink-2'"
          @click="emit('open')"
        >
          {{ name }}
        </button>
        <p class="truncate font-mono text-xs text-subtle">{{ role.key }}</p>
      </div>
      <div class="relative z-10 shrink-0">
        <DropdownMenu :items="items" align="end">
          <IconButton
            :icon="MoreHorizontal"
            :label="t('common.more')"
            variant="ghost"
            size="sm"
            :loading="busy"
            :tooltip="false"
          />
        </DropdownMenu>
      </div>
    </div>
    <p
      class="line-clamp-2 min-h-10 text-sm"
      :class="firstSentence(role.brief) ? 'text-muted' : 'text-subtle'"
    >
      {{ firstSentence(role.brief) || t('personas.noBrief') }}
    </p>
    <p class="flex min-w-0 items-center gap-1.5 border-t border-line pt-3 text-xs text-muted">
      <template v-if="broken || role.duplicate_id">
        <TriangleAlert :size="14" class="shrink-0 text-warning" aria-hidden="true" />
        <span class="truncate text-warning">
          {{ broken ? t('personas.broken') : t('personas.duplicate', { id: role.id }) }}
        </span>
      </template>
      <template v-else>
        <span v-if="role.scenes.length" class="flex shrink-0" aria-hidden="true">
          <span
            v-for="scene in role.scenes.slice(0, MAX_SCENES)"
            :key="scene"
            class="inline-flex rounded-[28%] ring-2 ring-surface not-first:-ml-1"
          >
            <Avatar :name="groupLabel(scene)" shape="square" :size="20" />
          </span>
        </span>
        <span class="truncate tabular">{{ usage }}</span>
      </template>
    </p>
  </article>
</template>
