<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { LogOut, Monitor, Moon, RotateCw, Sun } from '@lucide/vue'
import { setThemeMode, themeMode } from '../../composables/useThemeMode'
import { currentLocale, localeOptions, setLocale, type Locale } from '../../i18n'
import Popover from '../../ui/Popover.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'

withDefaults(
  defineProps<{ username: string; restartDisabled?: boolean; leaving: boolean; restartable?: boolean }>(),
  {
    restartable: true,
  },
)
const emit = defineEmits<{ restart: []; logout: [] }>()

const { t } = useI18n()
const open = ref(false)
const theme = computed({ get: () => themeMode.value as string, set: (value: string) => setThemeMode(value) })
const locale = computed({ get: () => currentLocale.value, set: (value: Locale) => void setLocale(value) })
const themes = computed(() => [
  { value: 'system', label: t('shell.account.themes.system'), icon: Monitor },
  { value: 'light', label: t('shell.account.themes.light'), icon: Sun },
  { value: 'dark', label: t('shell.account.themes.dark'), icon: Moon },
])
const item =
  'flex h-9 w-full cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-left text-sm text-ink-2 transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring disabled:cursor-not-allowed disabled:opacity-50'

function choose(event: 'restart' | 'logout') {
  open.value = false
  if (event === 'restart') emit('restart')
  else emit('logout')
}
</script>

<template>
  <Popover v-model:open="open" align="end" width="w-80">
    <template #trigger>
      <button
        type="button"
        class="inline-flex size-8 cursor-pointer items-center justify-center rounded-full bg-brand-soft text-sm font-semibold text-primary transition-transform hover:scale-105 focus-visible:focus-ring"
        :aria-label="t('shell.account.menu')"
      >
        {{ username.slice(0, 1).toUpperCase() || '?' }}
      </button>
    </template>
    <div class="-m-1 flex flex-col gap-3">
      <p class="truncate px-1 text-sm font-semibold">{{ username }}</p>
      <div class="flex flex-col gap-1.5">
        <span class="px-1 text-xs text-subtle">{{ t('shell.account.theme') }}</span>
        <SegmentedControl
          v-model="theme"
          :options="themes"
          size="sm"
          block
          :label="t('shell.account.theme')"
        />
      </div>
      <div class="flex flex-col gap-1.5">
        <span class="px-1 text-xs text-subtle">{{ t('shell.account.language') }}</span>
        <SegmentedControl
          v-model="locale"
          :options="localeOptions"
          size="sm"
          block
          :label="t('shell.account.language')"
        />
      </div>
      <div class="-mx-1 flex flex-col gap-0.5 border-t border-line pt-2">
        <button
          v-if="restartable"
          type="button"
          :class="item"
          :disabled="restartDisabled"
          @click="choose('restart')"
        >
          <RotateCw :size="15" class="text-muted" aria-hidden="true" />
          {{ t('shell.account.restart') }}
        </button>
        <button type="button" :class="item" :disabled="leaving" @click="choose('logout')">
          <LogOut :size="15" class="text-muted" aria-hidden="true" />
          {{ t('shell.account.logout') }}
        </button>
      </div>
    </div>
  </Popover>
</template>
