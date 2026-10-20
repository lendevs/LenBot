<script setup lang="ts">
import { computed, provide, ref, watch, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { TooltipProvider } from 'reka-ui'
import { ArrowLeft, ArrowRight, Check, Save } from '@lucide/vue'
import { forgetSetupToken, setupApi, setupToken, type SetupSaved } from '../../api/setup'
import markUrl from '../../assets/lenbot-mark-tile.svg'
import { currentLocale, localeOptions, setLocale, type Locale } from '../../i18n'
import Button from '../../ui/Button.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import Skeleton from '../../ui/Skeleton.vue'
import DonePanel from './DonePanel.vue'
import AccountStep from './steps/AccountStep.vue'
import ModelStep from './steps/ModelStep.vue'
import OwnerStep from './steps/OwnerStep.vue'
import PersonaStep from './steps/PersonaStep.vue'
import PlatformStep from './steps/PlatformStep.vue'
import PluginsStep from './steps/PluginsStep.vue'
import VectorStep from './steps/VectorStep.vue'
import { createWizard, steps, wizardKey, type Step } from './wizard'

const { t } = useI18n()
const queryClient = useQueryClient()
const wizard = createWizard()
provide(wizardKey, wizard)

const views: Record<Step, Component> = {
  account: AccountStep,
  platform: PlatformStep,
  owner: OwnerStep,
  model: ModelStep,
  vectors: VectorStep,
  persona: PersonaStep,
  plugins: PluginsStep,
}

const token = setupToken()
const current = ref(0)
/** The furthest step reached; earlier ones can be opened from the step list. */
const reached = ref(0)
const step = computed(() => steps[current.value])
const last = computed(() => current.value === steps.length - 1)

const setup = useQuery({
  queryKey: ['setup', 'protocols'],
  queryFn: setupApi.protocols,
  enabled: Boolean(token),
  staleTime: Infinity,
})
watch(
  () => setup.data.value,
  (value) => {
    if (!value) return
    wizard.protocols.value = value.protocols
    wizard.container.value = value.container
    if (value.container && value.panel_port) wizard.draft.port = value.panel_port
    wizard.settleProtocol()
  },
  { immediate: true },
)

function go(index: number) {
  current.value = index
  reached.value = Math.max(reached.value, index)
  window.scrollTo({ top: 0 })
}

/** Leaving a step shows its problems; the step only changes when there are none. */
function ready(index: number): boolean {
  wizard.tried.add(steps[index])
  return Object.keys(wizard.problems(steps[index])).length === 0
}

function next() {
  if (ready(current.value)) go(current.value + 1)
}

function skipVectors() {
  wizard.draft.vectorMode = 'skip'
  go(current.value + 1)
}

const saved = ref<SetupSaved | null>(null)
const save = useMutation({
  mutationFn: () => setupApi.save(wizard.body()),
  onSuccess: (result) => {
    wizard.clear()
    forgetSetupToken()
    saved.value = result
  },
  // A failed plugin installation is recorded; the list shows it.
  onError: () => queryClient.invalidateQueries({ queryKey: ['setup', 'plugins'] }),
})

function submit(withPlugins = true) {
  for (let index = 0; index < steps.length; index += 1) {
    if (!ready(index)) {
      go(index)
      return
    }
  }
  if (!withPlugins) wizard.draft.plugins = []
  save.mutate()
}

const locale = ref<Locale>(currentLocale.value)
function chooseLocale(value: Locale) {
  locale.value = value
  void setLocale(value)
}
const progress = computed(() => (saved.value ? 100 : (current.value / (steps.length - 1)) * 100))
</script>

<template>
  <!-- The wizard renders without the shell, so it provides the tooltips itself. -->
  <TooltipProvider :delay-duration="400">
    <main class="min-h-dvh bg-page lg:grid lg:grid-cols-[288px_minmax(0,1fr)]">
      <aside
        class="sticky top-0 hidden h-dvh flex-col gap-8 border-r border-line bg-sidebar px-6 py-8 lg:flex"
      >
        <div class="flex items-center gap-3">
          <img :src="markUrl" alt="" class="size-10 rounded-lg" />
          <div class="leading-tight">
            <p class="font-semibold text-ink">LenBot</p>
            <p class="text-sm text-muted">{{ t('setup.title') }}</p>
          </div>
        </div>
        <ol class="m-0 flex list-none flex-col gap-1 p-0" :aria-label="t('setup.stepsLabel')">
          <li v-for="(name, index) in steps" :key="name">
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left text-sm transition-colors focus-visible:focus-ring"
              :class="[
                index === current && !saved ? 'bg-selected font-medium text-ink' : 'text-muted',
                index <= reached && !saved
                  ? 'cursor-pointer hover:bg-hover hover:text-ink'
                  : 'cursor-default',
              ]"
              :aria-current="index === current && !saved ? 'step' : undefined"
              :disabled="index > reached || Boolean(saved) || save.isPending.value"
              @click="go(index)"
            >
              <span
                class="inline-flex size-6 shrink-0 items-center justify-center rounded-full border text-xs transition-colors"
                :class="
                  saved || index < current
                    ? 'border-brand bg-brand text-white'
                    : index === current
                      ? 'border-brand text-primary'
                      : 'border-line-strong'
                "
              >
                <Check v-if="saved || index < current" :size="13" :stroke-width="3" aria-hidden="true" />
                <template v-else>{{ index + 1 }}</template>
              </span>
              <span class="min-w-0 truncate">{{ t(`setup.steps.${name}`) }}</span>
            </button>
          </li>
        </ol>
        <div class="mt-auto">
          <SegmentedControl
            :model-value="locale"
            :options="localeOptions"
            size="sm"
            label="Language"
            @update:model-value="chooseLocale"
          />
        </div>
      </aside>

      <div class="flex min-w-0 flex-col">
        <div class="h-0.5 bg-track" aria-hidden="true">
          <div
            class="h-full bg-brand transition-[width] duration-300 ease-out"
            :style="{ width: `${progress}%` }"
          />
        </div>
        <header class="flex items-center justify-between gap-3 px-4 pt-4 lg:hidden">
          <div class="flex min-w-0 items-center gap-2.5">
            <img :src="markUrl" alt="" class="size-8 rounded-md" />
            <span class="truncate text-sm font-semibold">{{ t('setup.title') }}</span>
          </div>
          <SegmentedControl
            :model-value="locale"
            :options="localeOptions"
            size="sm"
            label="Language"
            @update:model-value="chooseLocale"
          />
        </header>

        <div class="flex-1 px-4 py-8 sm:px-8 lg:px-14 lg:py-14">
          <DonePanel v-if="saved" :result="saved" />
          <div v-else-if="!token" class="mx-auto w-full max-w-2xl">
            <ErrorNote :title="t('setup.noToken')" :error="t('setup.noTokenText')" />
          </div>
          <div v-else class="mx-auto flex w-full max-w-2xl flex-col gap-6">
            <ErrorNote
              v-if="setup.isError.value"
              :title="t('setup.readFailed')"
              :error="setup.error.value"
              :retry="setup.refetch"
            />
            <div class="flex flex-col gap-1">
              <p class="text-sm text-muted" role="status">
                {{ t('setup.stepOf', { n: current + 1, total: steps.length }) }}
              </p>
              <h1 class="text-2xl font-semibold text-ink">{{ t(`setup.steps.${step}`) }}</h1>
            </div>
            <Skeleton v-if="setup.isPending.value" :lines="6" />
            <form v-else :key="step" class="animate-rise" novalidate @submit.prevent>
              <component :is="views[step]" />
            </form>
            <ErrorNote v-if="save.isError.value" :title="t('setup.saveFailed')" :error="save.error.value" />
            <div class="flex flex-wrap items-center gap-2 border-t border-line pt-5">
              <Button
                v-if="current > 0"
                variant="ghost"
                :icon="ArrowLeft"
                :disabled="save.isPending.value"
                @click="go(current - 1)"
              >
                {{ t('setup.previous') }}
              </Button>
              <span class="flex-1" />
              <Button v-if="step === 'vectors'" variant="ghost" @click="skipVectors">
                {{ t('setup.skipVectors') }}
              </Button>
              <!-- On a phone the two ways to save stack under the back button, the main one first. -->
              <div v-if="last" class="flex w-full flex-col-reverse gap-2 sm:w-auto sm:flex-row">
                <Button :disabled="save.isPending.value" @click="submit(false)">
                  {{ t('setup.skipPlugins') }}
                </Button>
                <Button variant="primary" :icon="Save" :loading="save.isPending.value" @click="submit()">
                  {{
                    save.isPending.value && wizard.draft.plugins.length
                      ? t('setup.installing')
                      : t('setup.save')
                  }}
                </Button>
              </div>
              <Button v-else variant="primary" :icon-right="ArrowRight" @click="next">
                {{ t('setup.next') }}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </main>
  </TooltipProvider>
</template>
