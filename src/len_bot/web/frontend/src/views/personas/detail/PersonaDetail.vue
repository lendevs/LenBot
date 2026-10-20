<script setup lang="ts">
import { computed, provide, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Copy, Download, MoreHorizontal, Repeat } from '@lucide/vue'
import { personaAvatar } from '../../../api/host'
import type { PersonaRole } from '../../../api/personas'
import { useUnsavedChanges } from '../../../composables/useUnsavedChanges'
import { groupLabel } from '../../../layouts/shell/scenes'
import Avatar from '../../../ui/Avatar.vue'
import Badge from '../../../ui/Badge.vue'
import Button from '../../../ui/Button.vue'
import DropdownMenu, { type MenuEntry } from '../../../ui/DropdownMenu.vue'
import ErrorNote from '../../../ui/ErrorNote.vue'
import IconButton from '../../../ui/IconButton.vue'
import Skeleton from '../../../ui/Skeleton.vue'
import Tabs from '../../../ui/Tabs.vue'
import AbilitiesTab from './AbilitiesTab.vue'
import FilesTab from './FilesTab.vue'
import KnowledgeTab from './KnowledgeTab.vue'
import ProfileTab from './ProfileTab.vue'
import ScenesTab from './ScenesTab.vue'
import SpeechTab from './SpeechTab.vue'
import StickersTab from './StickersTab.vue'
import TrialTab from './TrialTab.vue'
import { profileKey, useProfileForm } from './profileForm'

const props = defineProps<{ role: PersonaRole; exporting?: boolean }>()
const emit = defineEmits<{ copy: []; export: [] }>()

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const name = computed(() => props.role.name || props.role.key)

const tabNames = ['profile', 'speech', 'knowledge', 'stickers', 'abilities', 'scenes', 'trial', 'files'] as const
type Tab = (typeof tabNames)[number]
const tab = computed<Tab>({
  get: () => (tabNames as readonly string[]).includes(route.query.tab as string) ? (route.query.tab as Tab) : 'profile',
  set: (value) => void router.replace({ query: { ...route.query, tab: value } }),
})
const tabs = computed(() =>
  tabNames.map((value) => ({
    value,
    label: t(`personas.detail.tabs.${value}`),
    count: value === 'scenes' ? props.role.scenes.length || undefined : undefined,
  })),
)

const form = useProfileForm(computed(() => props.role.key))
provide(profileKey, form)
// Tabs stay alive while switching, so each keeps its own draft and save bar.
const dirty = reactive({ knowledge: false, abilities: false, files: false })
useUnsavedChanges(
  computed(() => form.dirty.value.identity || form.dirty.value.speech || Object.values(dirty).some(Boolean)),
  { keep: ['tab'] },
)

const blocked = computed(() =>
  props.role.error
    ? t('personas.broken')
    : props.role.duplicate_id
      ? t('personas.detail.duplicate', { id: props.role.id })
      : null,
)
const usage = computed(() => {
  const names = props.role.scenes.map(groupLabel)
  if (!names.length) return t('personas.unused')
  return names.length > 3
    ? t('personas.usedMany', { names: names.slice(0, 3).join(t('personas.separator')), n: names.length })
    : t('personas.used', { names: names.join(t('personas.separator')) })
})
const menu = computed<MenuEntry[]>(() => [
  { label: t('personas.copy'), icon: Copy, disabled: Boolean(props.role.error), select: () => emit('copy') },
  { label: t('personas.export'), icon: Download, disabled: Boolean(props.role.error), select: () => emit('export') },
])
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <div>
      <Button variant="ghost" size="sm" :icon="ArrowLeft" :to="{ name: 'host-persona' }" class="-ml-2">
        {{ t('personas.all') }}
      </Button>
    </div>
    <header class="flex min-w-0 flex-wrap items-start gap-4">
      <Avatar :name="name" :src="personaAvatar(role)" :size="56" />
      <div class="flex min-w-0 flex-1 flex-col gap-1.5">
        <div class="flex min-w-0 flex-wrap items-center gap-2">
          <h1 class="truncate text-2xl font-semibold">{{ name }}</h1>
          <Badge v-if="role.id" class="font-mono">{{ role.id }}</Badge>
        </div>
        <p v-if="role.brief" class="line-clamp-2 max-w-3xl text-sm text-muted">{{ role.brief }}</p>
        <p class="flex min-w-0 items-center gap-1.5 text-sm text-muted">
          <span v-if="role.scenes.length" class="flex shrink-0" aria-hidden="true">
            <Avatar
              v-for="scene in role.scenes.slice(0, 4)"
              :key="scene"
              :name="groupLabel(scene)"
              shape="square"
              :size="20"
              class="ring-2 ring-page not-first:-ml-1"
            />
          </span>
          <span class="truncate">{{ usage }}</span>
        </p>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <Button
          variant="primary"
          :icon="Repeat"
          :disabled="Boolean(blocked)"
          @click="tab = 'scenes'"
        >
          {{ t('personas.detail.useIn') }}
        </Button>
        <DropdownMenu :items="menu">
          <IconButton :icon="MoreHorizontal" :label="t('common.more')" variant="secondary" :loading="exporting" :tooltip="false" />
        </DropdownMenu>
      </div>
    </header>

    <ErrorNote v-if="role.error" :title="t('personas.broken')" :error="role.error" />
    <template v-else>
      <p v-if="role.duplicate_id" class="rounded-md bg-warning-bg px-3 py-2 text-sm text-warning">{{ blocked }}</p>
      <Tabs v-model="tab" :items="tabs" :label="name" />
      <Skeleton v-if="form.saved.isPending.value" :lines="8" />
      <ErrorNote
        v-else-if="form.saved.isError.value"
        :title="t('personas.readFailed')"
        :error="form.saved.error.value"
        :retry="form.saved.refetch"
      />
      <KeepAlive v-else>
        <ProfileTab v-if="tab === 'profile'" :role="role" />
        <SpeechTab v-else-if="tab === 'speech'" />
        <KnowledgeTab v-else-if="tab === 'knowledge'" :persona="role.key" @dirty="(value) => (dirty.knowledge = value)" />
        <StickersTab v-else-if="tab === 'stickers'" :persona="role.key" />
        <AbilitiesTab v-else-if="tab === 'abilities'" :persona="role.key" @dirty="(value) => (dirty.abilities = value)" />
        <ScenesTab v-else-if="tab === 'scenes'" :role="role" :blocked="blocked" />
        <TrialTab v-else-if="tab === 'trial'" :role="role" />
        <FilesTab v-else :persona="role.key" @dirty="(value) => (dirty.files = value)" />
      </KeepAlive>
    </template>
  </div>
</template>
