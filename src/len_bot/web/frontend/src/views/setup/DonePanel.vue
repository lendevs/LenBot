<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowRight } from '@lucide/vue'
import type { SetupSaved } from '../../api/setup'
import markUrl from '../../assets/lenbot-mark-tile.svg'
import Button from '../../ui/Button.vue'
import Field from '../../ui/Field.vue'
import Input from '../../ui/Input.vue'

/** After saving: waits for the new panel and opens it; the address can be corrected by hand. */
const props = defineProps<{ result: SetupSaved }>()

const { t } = useI18n()
type State = 'starting' | 'ready' | 'slow' | 'failed'
const state = ref<State>('starting')

function panelAddress(): string {
  const panel = new URL(location.href)
  panel.hash = ''
  panel.search = ''
  panel.pathname = '/'
  // In a container the panel takes over this very port; otherwise it opens on its own.
  if (props.result.panel_url !== '/') panel.port = String(props.result.panel_port)
  return panel.href
}
const address = ref(panelAddress())
const addressError = ref<string | null>(null)
const installed = computed(() => props.result.plugins.map((item) => item.name))

let stopped = false
async function wait() {
  const panel = new URL(address.value)
  const begin = Date.now()
  while (!stopped && Date.now() - begin < 300_000) {
    try {
      const response = await fetch(new URL('/api/host/ready', panel), {
        cache: 'no-store',
        signal: AbortSignal.timeout(3000),
      })
      if (response.ok) {
        const ready = (await response.json()) as { ready?: boolean; status?: string }
        if (ready.ready) {
          state.value = 'ready'
          setTimeout(() => !stopped && location.assign(panel.href), 600)
          return
        }
        if (ready.status === 'failed') {
          state.value = 'failed'
          return
        }
      }
    } catch {
      // The panel is not listening yet.
    }
    if (Date.now() - begin > 30_000 && state.value === 'starting') state.value = 'slow'
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  if (!stopped) state.value = 'slow'
}
onMounted(wait)
onBeforeUnmount(() => (stopped = true))

function open() {
  let panel: URL
  try {
    panel = new URL(address.value)
  } catch {
    addressError.value = t('setup.problems.httpUrl')
    return
  }
  if (!['http:', 'https:'].includes(panel.protocol)) {
    addressError.value = t('setup.problems.httpUrl')
    return
  }
  addressError.value = null
  location.assign(panel.href)
}
</script>

<template>
  <section class="mx-auto flex w-full max-w-md animate-rise flex-col items-center gap-5 text-center">
    <img
      :src="markUrl"
      alt=""
      class="size-16 rounded-xl"
      :class="
        state === 'starting' || state === 'slow' ? 'animate-[setup-bob_1.6s_var(--ease-out)_infinite]' : ''
      "
    />
    <div class="flex flex-col gap-2" role="status">
      <h1 class="text-xl font-semibold">{{ t(`setup.done.${state}.title`) }}</h1>
      <p class="text-sm text-ink-2">{{ t(`setup.done.${state}.text`) }}</p>
      <p v-if="installed.length && state !== 'failed'" class="text-sm text-ink-2">
        {{ t('setup.done.plugins', { names: installed.join(t('setup.done.separator')) }) }}
      </p>
    </div>
    <div v-if="state === 'starting'" class="flex gap-1.5" aria-hidden="true">
      <span
        v-for="n in 3"
        :key="n"
        class="size-2 animate-pulse-dot rounded-full bg-brand"
        :style="{ animationDelay: `${n * 160}ms` }"
      />
    </div>
    <form class="flex w-full flex-col gap-3 text-left" novalidate @submit.prevent="open">
      <Field :label="t('setup.done.address')" :error="addressError" :info="t('setup.done.addressInfo')">
        <Input v-model="address" type="url" mono />
      </Field>
      <Button type="submit" variant="primary" :icon-right="ArrowRight" block>
        {{ t('setup.done.open') }}
      </Button>
    </form>
  </section>
</template>

<style>
@keyframes setup-bob {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-6px);
  }
}
</style>
