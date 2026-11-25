<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useResizeObserver } from '@vueuse/core'
import { TooltipProvider } from 'reka-ui'
import { logout, useAuth } from '../composables/useAuth'
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
const mainContent = ref<HTMLElement>()
const navEl = ref<HTMLElement>()
const indicator = ref({ left: 0, width: 0, ready: false })
const pages = computed(() => [
  { name: 'chat-test', label: t('chatTest.nav.chat') },
  { name: 'chat-test-settings', label: t('chatTest.nav.settings') },
])

function measureNav() {
  const active = navEl.value?.querySelector<HTMLElement>('[aria-current="page"]')
  if (!active) {
    indicator.value = { left: 0, width: 0, ready: indicator.value.ready }
    return
  }
  indicator.value = { left: active.offsetLeft, width: active.offsetWidth, ready: indicator.value.ready }
  if (!indicator.value.ready) requestAnimationFrame(() => (indicator.value.ready = true))
}

watch([() => route.name, pages], () => nextTick(measureNav))
onMounted(measureNav)
useResizeObserver(navEl, measureNav)

function skipToContent() {
  mainContent.value?.focus()
}

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
      <button
        type="button"
        class="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-(--z-toast) focus:inline-flex focus:h-9 focus:items-center focus:rounded-md focus:border focus:border-line-strong focus:bg-surface-raised focus:px-3 focus:text-sm focus:font-medium focus:text-ink focus:shadow-float focus:focus-ring"
        @click="skipToContent"
      >
        {{ t('shell.nav.skipToContent') }}
      </button>
      <header
        class="sticky top-0 z-(--z-top) flex h-14 shrink-0 items-center gap-3 border-b border-line bg-page px-3 sm:px-6"
      >
        <span class="flex shrink-0 items-center gap-2.5">
          <img :src="markUrl" alt="" class="size-7" />
          <strong class="text-base font-semibold tracking-tight max-sm:hidden">LenBot</strong>
        </span>
        <nav
          ref="navEl"
          class="relative flex min-w-0 items-center gap-0.5 rounded-lg bg-fill p-0.5"
          :aria-label="t('shell.nav.label')"
        >
          <span
            class="pointer-events-none absolute top-0.5 bottom-0.5 left-0 rounded-md bg-surface-raised shadow-card dark:bg-hover"
            :class="[
              indicator.ready && 'transition-[transform,width,opacity] duration-200 ease-out',
              indicator.width === 0 && 'opacity-0',
            ]"
            :style="{ width: `${indicator.width}px`, transform: `translateX(${indicator.left}px)` }"
            aria-hidden="true"
          />
          <RouterLink
            v-for="page in pages"
            :key="page.name"
            :to="{ name: page.name }"
            class="link-plain relative z-1 inline-flex h-7 items-center rounded-md px-3 text-sm font-medium whitespace-nowrap text-muted transition-colors hover:text-ink focus-visible:focus-ring aria-[current=page]:font-semibold aria-[current=page]:text-ink pointer-coarse:h-9"
            :aria-current="route.name === page.name ? 'page' : undefined"
          >
            {{ page.label }}
          </RouterLink>
        </nav>
        <div class="ml-auto flex shrink-0 items-center gap-2">
          <Badge tone="info">
            <span class="max-sm:hidden">{{ t('chatTest.mode') }}</span>
            <span class="sm:hidden">{{ t('shell.simulated') }}</span>
          </Badge>
          <AccountMenu
            :username="auth.user?.username ?? ''"
            :restartable="false"
            :leaving="leaving"
            @logout="exit"
          />
        </div>
      </header>
      <main
        id="main-content"
        ref="mainContent"
        tabindex="-1"
        class="grid w-full min-w-0 content-start gap-4 px-3 pt-4 pb-10 outline-none sm:px-4 sm:pt-6 sm:pb-12 lg:px-8 lg:pt-8 lg:pb-16"
      >
        <ErrorNote v-if="logoutError" :title="t('shell.account.logoutFailed')" :error="logoutError" />
        <slot />
      </main>
    </div>
    <ConfirmHost />
    <Toaster />
  </TooltipProvider>
</template>
