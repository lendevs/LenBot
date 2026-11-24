<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from '../../../ui/Button.vue'
import Dialog from '../../../ui/Dialog.vue'
import Field from '../../../ui/Field.vue'
import Input from '../../../ui/Input.vue'
import SegmentedControl from '../../../ui/SegmentedControl.vue'
import type { Member, MemberRole } from './members'

const ACCOUNT = /^[a-z][a-z0-9_-]*:[^:\s/\\]+$/

const props = defineProps<{
  member: Member | null
  adding: boolean
  removable: boolean
  existingUids: string[]
  botId?: string
  platform?: string
}>()
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
  (['member', 'admin', 'owner'] as MemberRole[]).map((value) => ({
    value,
    label: t(`playground.roles.${value}`),
  })),
)
const exampleAccount = computed(() => `${props.platform || 'onebot'}:10001`)
const nicknameError = computed(() => (draft.value.nickname.trim() ? null : t('playground.nicknameRequired')))
const uidError = computed(() => {
  const uid = draft.value.uid.trim()
  if (!ACCOUNT.test(uid)) return t('playground.accountInvalid', { example: exampleAccount.value })
  if (props.botId && uid === props.botId) return t('playground.accountIsBot')
  const original = props.adding ? null : props.member?.uid
  if (uid !== original && props.existingUids.includes(uid)) return t('playground.accountRepeated')
  return null
})
const valid = computed(() => !nicknameError.value && !uidError.value)

function submit() {
  if (!valid.value) return
  emit('save', {
    uid: draft.value.uid.trim(),
    nickname: draft.value.nickname.trim(),
    role: draft.value.role,
  })
  open.value = false
}
</script>

<template>
  <Dialog
    v-model:open="open"
    :title="adding ? t('playground.addMember') : t('playground.editMember')"
    size="sm"
  >
    <form id="member-form" class="flex flex-col gap-4" @submit.prevent="submit">
      <Field :label="t('playground.nickname')" required :error="nicknameError">
        <Input v-model="draft.nickname" autofocus />
      </Field>
      <Field :label="t('playground.account')" required :error="uidError">
        <Input v-model="draft.uid" mono :placeholder="exampleAccount" />
      </Field>
      <Field :label="t('playground.role')">
        <div><SegmentedControl v-model="draft.role" :options="roles" :label="t('playground.role')" /></div>
      </Field>
    </form>
    <template #footer>
      <div v-if="!adding && removable && member" class="mr-auto">
        <Button
          variant="danger-ghost"
          @click="
            () => {
              emit('remove', member!.uid)
              open = false
            }
          "
        >
          {{ t('common.delete') }}
        </Button>
      </div>
      <Button variant="ghost" @click="open = false">{{ t('common.cancel') }}</Button>
      <Button type="submit" form="member-form" variant="primary" :disabled="!valid">
        {{ t('common.save') }}
      </Button>
    </template>
  </Dialog>
</template>
