<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { LogIn } from '@lucide/vue'
import { login } from '../composables/useAuth'
import { returnPath } from '../router'
import { ApiError } from '../api/client'
import markUrl from '../assets/lenbot-mark-tile.svg'
import { localeOptions, currentLocale, setLocale, type Locale } from '../i18n'
import { describeError } from '../ui/errors'
import Button from '../ui/Button.vue'
import Field from '../ui/Field.vue'
import Input from '../ui/Input.vue'
import SegmentedControl from '../ui/SegmentedControl.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const username = ref(typeof route.query.username === 'string' ? route.query.username : '')
const prefilled = Boolean(username.value)
const password = ref('')
const busy = ref(false)
const error = ref('')
const shake = ref(0)
let attempt = 0

const locale = ref<Locale>(currentLocale.value)
function chooseLocale(value: Locale) {
  locale.value = value
  void setLocale(value)
}

async function submit() {
  if (busy.value || !username.value || !password.value) return
  const own = ++attempt
  const destination = returnPath(route.query.redirect)
  busy.value = true
  error.value = ''
  try {
    const accepted = await login(username.value, password.value)
    if (own !== attempt) return
    password.value = ''
    if (accepted) await router.replace(destination)
  } catch (problem) {
    if (own !== attempt) return
    error.value =
      problem instanceof ApiError && problem.status === 401
        ? t('login.invalid')
        : describeError(problem, t('ui.error.network')).message
    shake.value += 1
  } finally {
    if (own === attempt) busy.value = false
  }
}
</script>

<template>
  <main class="relative grid min-h-dvh place-items-center overflow-hidden bg-sidebar px-4 py-10">
    <div
      class="pointer-events-none absolute -top-40 left-1/2 size-[640px] -translate-x-1/2 rounded-full bg-brand opacity-[0.07] blur-3xl"
      aria-hidden="true"
    />
    <form
      :key="shake"
      class="relative flex w-full max-w-sm animate-rise flex-col gap-5 rounded-xl bg-surface p-7 shadow-dialog sm:p-8"
      :class="shake ? 'animate-[ui-shake_360ms_var(--ease-out)]' : ''"
      novalidate
      @submit.prevent="submit"
    >
      <img
        :src="markUrl"
        alt=""
        class="size-11 rounded-lg transition-transform duration-300 ease-out hover:-rotate-8"
      />
      <h1 class="text-xl font-semibold">{{ t('login.title') }}</h1>
      <Field :label="t('login.username')">
        <Input v-model="username" autocomplete="username" :disabled="busy" :autofocus="!prefilled" />
      </Field>
      <Field :label="t('login.password')" :error="error || null">
        <Input
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
    <div class="absolute right-4 bottom-4">
      <SegmentedControl
        :model-value="locale"
        :options="localeOptions"
        size="sm"
        label="Language"
        @update:model-value="chooseLocale"
      />
    </div>
  </main>
</template>
