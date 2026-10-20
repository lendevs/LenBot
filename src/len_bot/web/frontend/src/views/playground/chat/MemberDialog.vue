<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from '../../../ui/Button.vue'
import Dialog from '../../../ui/Dialog.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import type { Member, MemberRole } from './members'

const props = defineProps<{ member: Member | null; adding: boolean; removable: boolean }>()
const open = defineModel<boolean>('open', { required: true })
const emit = defineEmits<{ save: [member: Member]; remove: [uid: string] }>()

const { t } = useI18n()
const draft = ref<Member>({ uid: '', nickname: '', role: 'member' })
watch(
  () => [open.value, props.member] as const,
  ([visible, member]) => {
    if (visible && member) draft.value = { ...member }
  },
  { immediate: true },
)
const roles = computed(() =>
  (['member', 'admin', 'owner'] as MemberRole[]).map((value) => ({ value, label: t(`playground.roles.${value}`) })),
)
function submit() {
  if (!draft.value.nickname.trim()) return
  emit('save', draft.value)
  open.value = false
}
</script>

<template>
  <Dialog v-model:open="open" :title="adding ? t('playground.addMember') : t('playground.editMember')" size="sm">
    <form id="member-form" class="flex flex-col gap-4" @submit.prevent="submit">
      <Field :label="t('playground.nickname')" required :error="draft.nickname.trim() ? null : t('playground.nicknameRequired')">
        <Input v-model="draft.nickname" autofocus />
      </Field>
      <Field :label="t('playground.account')">
        <Input :model-value="draft.uid" mono readonly />
      </Field>
      <Field :label="t('playground.role')">
        <div><SegmentedControl v-model="draft.role" :options="roles" :label="t('playground.role')" /></div>
      </Field>
    </form>
    <template #footer>
      <Button
        v-if="!adding && removable"
        variant="danger-ghost"
        class="mr-auto"
        @click="
          () => {
            emit('remove', draft.uid)
            open = false
          }
        "
      >
        {{ t('common.delete') }}
      </Button>
      <Button variant="ghost" @click="open = false">{{ t('common.cancel') }}</Button>
      <Button type="submit" form="member-form" variant="primary" :disabled="!draft.nickname.trim()">{{ t('common.save') }}</Button>
    </template>
  </Dialog>
</template>
