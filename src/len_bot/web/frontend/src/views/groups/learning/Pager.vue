<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import { formatNumber } from '../../../i18n/format'
import IconButton from '../../../ui/IconButton.vue'

defineProps<{ offset: number; limit: number; total: number; disabled?: boolean }>()
const emit = defineEmits<{ move: [step: -1 | 1] }>()
const { t } = useI18n()
</script>

<template>
  <div v-if="offset > 0 || total > limit" class="flex items-center justify-center gap-2 text-sm text-muted">
    <IconButton
      :icon="ChevronLeft"
      :label="t('groups.learning.previous')"
      variant="ghost"
      size="sm"
      :disabled="disabled || offset === 0"
      @click="emit('move', -1)"
    />
    <span class="tabular">
      {{
        t('groups.learning.page', {
          page: formatNumber(Math.floor(offset / limit) + 1),
          pages: formatNumber(Math.ceil(total / limit)),
          total: formatNumber(total),
        })
      }}
    </span>
    <IconButton
      :icon="ChevronRight"
      :label="t('groups.learning.next')"
      variant="ghost"
      size="sm"
      :disabled="disabled || offset + limit >= total"
      @click="emit('move', 1)"
    />
  </div>
</template>
