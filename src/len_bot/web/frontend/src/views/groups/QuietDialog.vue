<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { hostApi, type SceneControl } from '../../api/host'
import { keys } from '../../api/query'
import { currentLocale } from '../../i18n'
import { formatDateTime } from '../../i18n/format'
import { readHostState } from '../../api/hostStore'
import Button from '../../ui/Button.vue'
import Dialog from '../../ui/Dialog.vue'
import ErrorNote from '../../ui/ErrorNote.vue'
import Field from '../../ui/Field.vue'
import RadioGroup from '../../ui/RadioGroup.vue'
import SegmentedControl from '../../ui/SegmentedControl.vue'
import { toast } from '../../ui/toast'

const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{ scene: string; timeZone: string }>()

const { t } = useI18n()
const client = useQueryClient()
const minutes = ref<'30' | '60' | '180' | '480'>('60')
const direct = ref<'allow' | 'defer'>('allow')

const unit = (n: number, name: 'minute' | 'hour') =>
  new Intl.NumberFormat(currentLocale.value, { style: 'unit', unit: name, unitDisplay: 'long' }).format(n)
const durations = computed(() => [
  { value: '30' as const, label: unit(30, 'minute') },
  { value: '60' as const, label: unit(1, 'hour') },
  { value: '180' as const, label: unit(3, 'hour') },
  { value: '480' as const, label: unit(8, 'hour') },
])

const quiet = useMutation({
  mutationFn: () => hostApi.quiet(props.scene, Number(minutes.value) * 60, direct.value),
  onSuccess: (control: SceneControl) => {
    client.setQueryData(keys.scene.control(props.scene), control)
    void readHostState()
    open.value = false
    const until = control.temporary_quiet?.until
    toast.success(
      until
        ? t('groups.quiet.started', { time: formatDateTime(until, { timeZone: props.timeZone }) })
        : t('common.saved'),
    )
  },
})
watch(open, (value) => {
  if (value) quiet.reset()
})
</script>

<template>
  <Dialog v-model:open="open" :title="t('groups.quiet.title')" size="sm" :busy="quiet.isPending.value">
    <div class="flex flex-col gap-5">
      <Field :label="t('groups.quiet.duration')">
        <SegmentedControl v-model="minutes" :options="durations" block :label="t('groups.quiet.duration')" />
      </Field>
      <Field :label="t('groups.quiet.direct')">
        <RadioGroup
          v-model="direct"
          :options="[
            { value: 'allow', label: t('groups.quiet.allow') },
            { value: 'defer', label: t('groups.quiet.defer') },
          ]"
        />
      </Field>
      <ErrorNote v-if="quiet.isError.value" :title="t('groups.quiet.failed')" :error="quiet.error.value" />
    </div>
    <template #footer>
      <Button variant="ghost" :disabled="quiet.isPending.value" @click="open = false">
        {{ t('common.cancel') }}
      </Button>
      <Button variant="primary" :loading="quiet.isPending.value" @click="quiet.mutate()">
        {{ t('groups.quiet.start') }}
      </Button>
    </template>
  </Dialog>
</template>
