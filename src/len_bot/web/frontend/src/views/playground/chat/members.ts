import { computed, ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'

export type MemberRole = 'member' | 'admin' | 'owner'
export interface Member {
  uid: string
  nickname: string
  role: MemberRole
}

const storageKey = (scene: string) => `lenbot.chatTest.members.${scene}`
function read(scene: string): Member[] | null {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey(scene)) ?? 'null') as unknown
    return Array.isArray(saved) && saved.length ? (saved as Member[]) : null
  } catch {
    return null
  }
}
function write(scene: string, members: Member[]) {
  try {
    localStorage.setItem(storageKey(scene), JSON.stringify(members))
  } catch {
    // Without storage the members last until the page is closed.
  }
}

/**
 * The simulated people who speak in a test, kept per group in this browser. A private chat has exactly one:
 * the other side of the conversation, whose account the scene fixes.
 */
export function useMembers(scene: Ref<string | undefined>, isPrivate: Ref<boolean>) {
  const { t } = useI18n()
  const members = ref<Member[]>([])
  const current = ref('')
  watch(
    scene,
    (value) => {
      if (!value) return
      if (isPrivate.value) {
        const [platform, , ...rest] = value.split(':')
        members.value = [
          { uid: `${platform}:${rest.join(':')}`, nickname: t('playground.other'), role: 'member' },
        ]
      } else
        members.value = read(value) ?? [
          { uid: 'onebot:10001', nickname: t('playground.sampleA'), role: 'member' },
          { uid: 'onebot:10002', nickname: t('playground.sampleB'), role: 'member' },
        ]
      current.value = members.value[0]!.uid
    },
    { immediate: true },
  )
  watch(
    members,
    (value) => {
      if (scene.value && !isPrivate.value) write(scene.value, value)
    },
    { deep: true },
  )
  const speaker = computed(
    () => members.value.find((member) => member.uid === current.value) ?? members.value[0],
  )

  function nextUid() {
    const used = new Set(members.value.map((member) => member.uid))
    let number = 10001
    while (used.has(`onebot:${number}`)) number++
    return `onebot:${number}`
  }
  function save(member: Member, adding: boolean) {
    const clean = { ...member, nickname: member.nickname.trim() }
    members.value = adding
      ? [...members.value, clean]
      : members.value.map((item) => (item.uid === clean.uid ? clean : item))
    current.value = clean.uid
  }
  function remove(uid: string) {
    members.value = members.value.filter((item) => item.uid !== uid)
    if (current.value === uid) current.value = members.value[0]!.uid
  }
  return { members, current, speaker, nextUid, save, remove }
}
