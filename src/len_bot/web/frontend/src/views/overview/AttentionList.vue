<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown, CircleCheck, X } from '@lucide/vue'
import Badge, { type Tone } from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import CodeBlock from '../../ui/CodeBlock.vue'
import Collapsible from '../../ui/Collapsible.vue'
import IconButton from '../../ui/IconButton.vue'
import Skeleton from '../../ui/Skeleton.vue'
import StatusDot from '../../ui/StatusDot.vue'
import type { Attention } from './attention'

const props = defineProps<{ items: Attention[]; loading: boolean }>()
const emit = defineEmits<{ dismiss: [item: Attention] }>()

const { t } = useI18n()

const badgeTone = computed<Tone>(() =>
  props.items.some((item) => item.tone === 'error')
    ? 'error'
    : props.items.some((item) => item.tone === 'warning')
      ? 'warning'
      : 'info',
)
</script>

<template>
  <section class="flex min-w-0 flex-col gap-3">
    <h2 class="flex items-center gap-2 text-base font-semibold text-ink">
      {{ t('overview.todo.title') }}
      <Badge v-if="items.length" :tone="badgeTone">
        <span class="tabular">{{ items.length }}</span>
      </Badge>
    </h2>
    <div v-if="loading" class="flex flex-col divide-y divide-line border-y border-line" aria-hidden="true">
      <div v-for="n in 2" :key="n" class="flex items-center gap-3 py-3">
        <Skeleton width="8px" height="8px" rounded="rounded-full" />
        <Skeleton width="68%" height="15px" />
      </div>
    </div>
    <p
      v-else-if="!items.length"
      class="flex items-center gap-2 border-t border-line pt-3.5 text-sm text-ink-2"
    >
      <CircleCheck :size="16" class="shrink-0 text-success" aria-hidden="true" />
      <span>{{ t('overview.todo.none') }}</span>
    </p>
    <TransitionGroup
      v-else
      tag="ul"
      name="ui-list"
      leave-active-class="ui-list-leave-active pointer-events-none absolute inset-x-0"
      class="relative flex list-none flex-col divide-y divide-line border-y border-line"
    >
      <li v-for="item in items" :key="item.key" class="py-3">
        <Collapsible v-if="item.children" variant="bare">
          <template #trigger="{ open }">
            <button
              type="button"
              class="flex min-w-0 flex-1 cursor-pointer items-center gap-3 rounded-sm text-left focus-visible:focus-ring"
            >
              <StatusDot :tone="item.tone" />
              <span class="min-w-0 flex-1 text-sm text-ink tabular">{{ item.text }}</span>
              <span class="shrink-0 text-xs text-muted tabular">
                {{ t('overview.todo.groups', { n: item.children.length }, item.children.length) }}
              </span>
              <ChevronDown
                :size="16"
                class="shrink-0 text-muted transition-transform duration-(--dur-2)"
                :class="open && 'rotate-180'"
                aria-hidden="true"
              />
            </button>
          </template>
          <template #end>
            <IconButton
              :icon="X"
              :label="t('overview.todo.dismiss')"
              size="sm"
              @click="emit('dismiss', item)"
            />
          </template>
          <TransitionGroup
            tag="ul"
            name="ui-list"
            leave-active-class="ui-list-leave-active pointer-events-none absolute inset-x-0"
            class="relative mt-2.5 flex list-none flex-col gap-1.5 border-l-2 border-line pl-3.5"
          >
            <li v-for="child in item.children" :key="child.key" class="flex min-w-0 flex-col gap-1.5 py-1">
              <div class="flex min-w-0 items-center gap-3">
                <span class="min-w-0 flex-1 text-sm text-ink-2 tabular">{{ child.text }}</span>
                <Button v-if="child.to" size="sm" variant="ghost" :to="child.to">{{ child.action }}</Button>
                <IconButton
                  :icon="X"
                  :label="t('overview.todo.dismiss')"
                  size="sm"
                  @click="emit('dismiss', child)"
                />
              </div>
              <Collapsible v-if="child.error" variant="inline" :title="t('common.rawError')">
                <CodeBlock :code="child.error" :max-lines="8" />
              </Collapsible>
            </li>
          </TransitionGroup>
        </Collapsible>
        <div v-else class="flex min-w-0 flex-col gap-1.5">
          <div class="flex min-w-0 items-center gap-3">
            <StatusDot :tone="item.tone" />
            <span class="min-w-0 flex-1 text-sm text-ink tabular">{{ item.text }}</span>
            <Button v-if="item.to" size="sm" :to="item.to">{{ item.action }}</Button>
            <IconButton
              :icon="X"
              :label="t('overview.todo.dismiss')"
              size="sm"
              @click="emit('dismiss', item)"
            />
          </div>
          <div v-if="item.error" class="pl-5">
            <Collapsible variant="inline" :title="t('common.rawError')">
              <CodeBlock :code="item.error" :max-lines="8" />
            </Collapsible>
          </div>
        </div>
      </li>
    </TransitionGroup>
  </section>
</template>
