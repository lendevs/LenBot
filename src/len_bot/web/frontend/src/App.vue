<script setup lang="ts">
import { defineAsyncComponent, onScopeDispose, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuth, refreshAuth } from './composables/useAuth'
import { areaOf } from './layouts/nav'
import ErrorNote from './ui/ErrorNote.vue'
import Spinner from './ui/Spinner.vue'

// Shells load after login, so the login page does not wait for them.
const TrialShell = defineAsyncComponent(() => import('./layouts/TrialShell.vue'))
const AppShell = defineAsyncComponent(() => import('./layouts/AppShell.vue'))

const { t } = useI18n()
const auth = useAuth()
const route = useRoute()
const router = useRouter()

const sameArea = ref(false)
const stopResolve = router.beforeResolve((to, from) => {
  const nextArea = areaOf(to.name)
  const prevArea = areaOf(from.name)
  sameArea.value =
    (nextArea !== undefined && nextArea === prevArea) ||
    (String(to.name).startsWith('chat-test') && String(from.name).startsWith('chat-test'))
})
onScopeDispose(stopResolve)

async function retry() {
  await refreshAuth()
  if (auth.status === 'unauthenticated')
    await router.replace({ name: 'login', query: { redirect: route.fullPath } })
}
</script>

<template>
  <router-view v-if="route.meta.bare" />
  <div
    v-else-if="auth.status === 'loading'"
    class="grid min-h-dvh place-items-center bg-page text-muted"
    role="status"
  >
    <Spinner :size="22" :label="t('login.checking')" />
  </div>
  <div
    v-else-if="auth.status === 'error'"
    class="mx-auto flex min-h-dvh max-w-lg flex-col justify-center px-4 py-8"
  >
    <ErrorNote :title="t('login.checkFailed')" :error="auth.error" :retry="retry" />
  </div>
  <router-view v-else-if="route.name === 'login'" />
  <component
    :is="auth.panelContext?.mode === 'isolated-multi' ? AppShell : TrialShell"
    v-else-if="auth.status === 'authenticated' && auth.panelContext"
  >
    <router-view v-slot="{ Component, route: page }">
      <transition
        :name="sameArea ? undefined : 'page'"
        :enter-active-class="sameArea ? 'transition-opacity duration-(--dur-2) ease-out' : undefined"
        :leave-active-class="sameArea ? 'transition-opacity duration-(--dur-1) ease-in' : undefined"
        :enter-from-class="sameArea ? 'opacity-0' : undefined"
        :leave-to-class="sameArea ? 'opacity-0' : undefined"
        mode="out-in"
      >
        <component :is="Component" :key="page.name" />
      </transition>
    </router-view>
  </component>
</template>
