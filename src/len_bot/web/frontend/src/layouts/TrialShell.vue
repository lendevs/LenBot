<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { TooltipProvider } from 'reka-ui'
import { logout, useAuth } from '../composables/useAuth.js'
import markUrl from '../assets/lenbot-mark.svg'
import Badge from '../ui/Badge.vue'
import ConfirmHost from '../ui/ConfirmHost.vue'
import ErrorNote from '../ui/ErrorNote.vue'
import Toaster from '../ui/Toaster.vue'
import { confirm } from '../ui/confirm'
import AccountMenu from './shell/AccountMenu.vue'

/** Shell of a standalone chat-test instance: one test scene, two pages, no host controls. */
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuth()
const leaving = ref(false)
const logoutError = ref<unknown>(null)
const pages = computed(() => [
  { name: 'chat-test', label: t('chatTest.nav.chat') },
  { name: 'chat-test-settings', label: t('chatTest.nav.settings') },
])

async function exit() {
  if (leaving.value) return
  const confirmed = await confirm({
    title: t('shell.account.logoutTitle'),
    message: t('shell.account.logoutMessage'),
    confirmLabel: t('shell.account.logout'),
  })
  if (!confirmed) return
  leaving.value = true
  logoutError.value = null
  try {
    await logout()
    if (useAuth().status === 'unauthenticated') await router.replace({ name: 'login' })
  } catch (error) {
    logoutError.value = error
  } finally {
    leaving.value = false
  }
}
</script>

<template>
  <TooltipProvider :delay-duration="400">
    <div class="flex min-h-dvh flex-col bg-page text-ink">
      <header
        class="sticky top-0 z-(--z-top) flex h-14 shrink-0 items-center gap-3 border-b border-line bg-page/85 px-3 backdrop-blur-md sm:px-6"
      >
        <span class="flex shrink-0 items-center gap-2.5">
          <img :src="markUrl" alt="" class="size-7" />
          <strong class="text-lg font-semibold max-sm:hidden">LenBot</strong>
        </span>
        <nav class="flex min-w-0 items-center gap-1" :aria-label="t('shell.nav.label')">
          <RouterLink
            v-for="page in pages"
            :key="page.name"
            :to="{ name: page.name }"
            class="link-plain inline-flex h-8 items-center rounded-md px-2.5 text-sm whitespace-nowrap text-ink-2 transition-colors hover:bg-hover hover:text-ink focus-visible:focus-ring aria-[current=page]:bg-surface aria-[current=page]:font-semibold aria-[current=page]:text-ink aria-[current=page]:shadow-card"
            :aria-current="route.name === page.name ? 'page' : undefined"
          >
            {{ page.label }}
          </RouterLink>
        </nav>
        <div class="ml-auto flex items-center gap-2">
          <Badge tone="info" class="max-sm:hidden">{{ t('chatTest.mode') }}</Badge>
          <AccountMenu
            :username="auth.user?.username ?? ''"
            :restartable="false"
            :leaving="leaving"
            @logout="exit"
          />
        </div>
      </header>
      <main id="main-content" class="shell-main">
        <ErrorNote v-if="logoutError" :title="t('shell.account.logoutFailed')" :error="logoutError" />
        <slot />
      </main>
    </div>
    <ConfirmHost />
    <Toaster />
  </TooltipProvider>
</template>
