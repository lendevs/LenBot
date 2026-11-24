<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useMediaQuery } from '@vueuse/core'
import { TooltipProvider } from 'reka-ui'
import { LogIn, Moon, Sun } from '@lucide/vue'
import { login } from '../composables/useAuth'
import { setThemeMode, themeMode } from '../composables/useThemeMode'
import { returnPath } from '../router'
import { ApiError } from '../api/client'
import markUrl from '../assets/lenbot-mark-tile.svg'
import { localeOptions, currentLocale, setLocale, type Locale } from '../i18n'
import { describeError } from '../ui/errors'
import Button from '../ui/Button.vue'
import Field from '../ui/Field.vue'
import IconButton from '../ui/IconButton.vue'
import Input from '../ui/Input.vue'
import SegmentedControl from '../ui/SegmentedControl.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const username = ref(typeof route.query.username === 'string' ? route.query.username : '')
const prefilled = Boolean(username.value)
const password = ref('')
const passwordInput = ref<InstanceType<typeof Input>>()
const busy = ref(false)
const error = ref('')
const shaking = ref(false)
let shakeFrame = 0
let attempt = 0

const prefersDark = useMediaQuery('(prefers-color-scheme: dark)')
const isDark = computed(
  () => themeMode.value === 'dark' || (themeMode.value === 'system' && prefersDark.value),
)
function toggleTheme() {
  setThemeMode(isDark.value ? 'light' : 'dark')
}

const locale = ref<Locale>(currentLocale.value)
function chooseLocale(value: Locale) {
  locale.value = value
  void setLocale(value)
}

function triggerShake() {
  cancelAnimationFrame(shakeFrame)
  shaking.value = false
  shakeFrame = requestAnimationFrame(() => {
    shaking.value = true
  })
}

onBeforeUnmount(() => cancelAnimationFrame(shakeFrame))

async function submit() {
  if (busy.value || !username.value || !password.value) return
  const own = ++attempt
  const destination = returnPath(route.query.redirect)
  busy.value = true
  error.value = ''
  let failed = false
  try {
    const accepted = await login(username.value, password.value)
    if (own !== attempt) return
    password.value = ''
    if (accepted) await router.replace(destination)
  } catch (problem) {
    if (own !== attempt) return
    failed = true
    error.value =
      problem instanceof ApiError && problem.status === 401
        ? t('login.invalid')
        : describeError(problem, t('ui.error.network')).message
    triggerShake()
  } finally {
    if (own === attempt) busy.value = false
  }
  if (failed && own === attempt) {
    await nextTick()
    passwordInput.value?.focus()
    passwordInput.value?.select()
  }
}
</script>

<template>
  <TooltipProvider :delay-duration="400">
    <main class="flex min-h-dvh flex-col justify-between bg-sidebar px-4 py-6 sm:px-6 sm:py-8">
      <div aria-hidden="true" />
      <div class="mx-auto my-8 w-full max-w-sm animate-rise">
        <form
          class="flex w-full flex-col gap-5 rounded-xl border border-line bg-surface p-6 shadow-card sm:p-8"
          :class="shaking && 'animate-[ui-shake_360ms_var(--ease-out)]'"
          novalidate
          @animationend="shaking = false"
          @submit.prevent="submit"
        >
          <div class="flex flex-col gap-3">
            <img
              :src="markUrl"
              alt=""
              class="size-11 rounded-lg transition-transform duration-300 ease-out hover:-rotate-8"
            />
            <h1 class="text-xl font-semibold tracking-tight text-ink">{{ t('login.title') }}</h1>
          </div>
          <Field :label="t('login.username')">
            <Input v-model="username" autocomplete="username" :disabled="busy" :autofocus="!prefilled" />
          </Field>
          <Field :label="t('login.password')" :error="error || null">
            <Input
              ref="passwordInput"
              v-model="password"
              type="password"
              autocomplete="current-password"
              :disabled="busy"
              :autofocus="prefilled"
            />
          </Field>
          <Button
            type="submit"
            variant="primary"
            size="lg"
            block
            :icon="LogIn"
            :loading="busy"
            :disabled="!username || !password"
          >
            {{ t('login.submit') }}
          </Button>
        </form>
      </div>
      <div class="flex items-center justify-end gap-2">
        <IconButton
          :icon="isDark ? Sun : Moon"
          :label="t(isDark ? 'login.switchToLight' : 'login.switchToDark')"
          size="sm"
          variant="secondary"
          @click="toggleTheme"
        />
        <SegmentedControl
          :model-value="locale"
          :options="localeOptions"
          size="sm"
          :label="t('shell.account.language')"
          @update:model-value="chooseLocale"
        />
      </div>
    </main>
  </TooltipProvider>
</template>
