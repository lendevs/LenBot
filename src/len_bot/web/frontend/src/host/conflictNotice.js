import { nextTick, ref, watch } from 'vue'

// The B-2 conflict notice ("没有保存：…请重新填写后再保存") stays until the next save, or until the
// user starts over: once they edit the reloaded form and then discard or undo those edits (the
// form is clean again), the notice no longer describes the page and is cleared.
export function useConflictNotice(dirty) {
  const conflict = ref('')
  let edited = false
  watch(dirty, value => {
    if (value) edited = true
    else if (edited) {
      edited = false
      conflict.value = ''
    }
  })
  async function show(text) {
    // Let the form reload from the server snapshot first, so that reset does not clear the notice.
    await nextTick()
    edited = false
    conflict.value = text
  }
  function clear() {
    conflict.value = ''
  }
  return { conflict, show, clear }
}
