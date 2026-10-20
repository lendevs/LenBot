<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RotateCw } from '@lucide/vue'
import { currentLocale } from '../../i18n'
import Button from '../../ui/Button.vue'
import Dialog from '../../ui/Dialog.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Skeleton from '../../ui/Skeleton.vue'
import { sectionKey } from '../nav'
import { confirmRestart, newPanelUrl, panelChanged, restartFlow as flow, waitForRestart } from './restart'
import { groupLabel } from './scenes'

const { t } = useI18n()
const list = computed(() => new Intl.ListFormat(currentLocale.value, { type: 'conjunction' }))
const preview = computed(() => flow.preview)
const pending = computed(() => {
  const value = preview.value
  if (!value) return []
  return [
    ...new Set([
      ...value.pending.sections.map((section) => t(sectionKey(section))),
      ...value.pending.scenes.map(groupLabel),
      ...value.pending.plugins.map((item) =>
        t('shell.restart.dialog.plugin', { name: item.name, version: item.candidate.version }),
      ),
      ...value.pending.personas.map((item) => t('shell.restart.persona', { name: item.name })),
    ]),
  ]
})
const failedPlugins = computed(() => preview.value?.pending.plugins.filter((item) => item.error) ?? [])
const link = computed(() => (preview.value ? newPanelUrl(preview.value) : null))
const moved = computed(() => (preview.value ? panelChanged(preview.value) : false))
const connectionError = computed(() => {
  const error = flow.lastConnectionError
  return error instanceof Error ? error.message : error ? String(error) : ''
})
</script>

<template>
  <Dialog v-model:open="flow.open" :title="t('shell.account.restart')" :busy="flow.busy || flow.waiting">
    <div class="flex flex-col gap-3 text-sm text-ink-2 [overflow-wrap:anywhere]">
      <Skeleton v-if="flow.busy && !preview" :lines="4" />
      <ErrorNote v-if="flow.error" :title="t('shell.restart.dialog.failed')" :error="flow.error" />
      <template v-if="preview && flow.phase === 'preview'">
        <p>
          {{
            pending.length
              ? t('shell.restart.dialog.pending', { items: list.format(pending) })
              : t('shell.restart.dialog.nothing')
          }}
        </p>
        <ErrorNote
          v-for="item in failedPlugins"
          :key="item.name"
          :title="t('shell.restart.dialog.pluginFailed', { name: item.name })"
          :error="item.error"
        />
        <p>{{ t('shell.restart.dialog.relogin') }}</p>
        <p v-if="preview.chats.length">
          {{ t('shell.restart.dialog.chats', { names: list.format(preview.chats.map(groupLabel)) }) }}
        </p>
        <div v-if="preview.tasks.length">
          <p>{{ t('shell.restart.dialog.tasks') }}</p>
          <ul class="mt-1 list-disc pl-5">
            <li v-for="task in preview.tasks" :key="task.id">
              #{{ task.id }} · {{ groupLabel(task.scene) }} · {{ task.goal
              }}{{ task.account_browser ? t('shell.restart.dialog.accountBrowser') : '' }}
            </li>
          </ul>
        </div>
        <p v-if="preview.queued_tasks">{{ t('shell.restart.dialog.queued', { n: preview.queued_tasks }) }}</p>
        <p v-if="preview.browsers.length">
          {{
            t('shell.restart.dialog.browsers', {
              items: list.format(
                preview.browsers.map(
                  (item) => `#${item.id} · ${item.session || t('shell.restart.dialog.creating')}`,
                ),
              ),
            })
          }}
        </p>
        <p v-if="preview.trials.length">
          {{ t('shell.restart.dialog.trials', { n: preview.trials.length }) }}
        </p>
        <p v-if="moved">
          {{ t('shell.restart.dialog.newAddress') }}
          <a v-if="link" :href="link" class="text-primary underline-offset-2 hover:underline">{{ link }}</a>
          <span v-else>{{ t('shell.restart.dialog.addressInLog') }}</span>
          {{ t('shell.restart.dialog.proxy') }}
        </p>
        <p v-if="!preview.restartable" class="rounded-lg bg-warning-bg px-4 py-3 text-ink" role="alert">
          {{ t('shell.restart.dialog.notRestartable') }}
        </p>
      </template>
      <p v-if="flow.phase === 'waiting'" class="flex items-center gap-2" role="status">
        <RotateCw :size="16" class="animate-spin text-primary" aria-hidden="true" />
        {{ t('shell.restart.dialog.waiting') }}
      </p>
      <p v-if="flow.phase === 'ready'" role="status">{{ t('shell.restart.dialog.ready') }}</p>
      <p v-if="flow.phase === 'address-changed'">
        <template v-if="link">
          {{ t('shell.restart.dialog.moved') }}
          <a :href="link" class="text-primary underline-offset-2 hover:underline">{{ link }}</a>
        </template>
        <template v-else>{{ t('shell.restart.dialog.movedInLog') }}</template>
      </p>
      <p v-if="flow.phase === 'unavailable' && connectionError" class="text-muted">
        {{ t('shell.restart.dialog.unreachable', { error: connectionError }) }}
      </p>
    </div>
    <template v-if="flow.phase === 'preview' || flow.phase === 'unavailable'" #footer>
      <template v-if="flow.phase === 'preview'">
        <Button variant="ghost" :disabled="flow.busy" @click="flow.open = false">
          {{ t('shell.restart.dialog.later') }}
        </Button>
        <Button
          variant="primary"
          :icon="RotateCw"
          :loading="flow.busy && Boolean(preview)"
          :disabled="!preview?.restartable"
          @click="confirmRestart"
        >
          {{ t('shell.restart.dialog.confirm') }}
        </Button>
      </template>
      <Button v-else variant="primary" @click="waitForRestart">{{ t('shell.restart.dialog.check') }}</Button>
    </template>
  </Dialog>
</template>
