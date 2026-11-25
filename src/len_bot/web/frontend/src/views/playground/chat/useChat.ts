import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { keys } from '../../../api/query'
import { chatApi, type ChatSource } from '../../../api/trials'
import { isPrivateScene } from '../../../layouts/shell/scenes'

export type LiveStatus = 'connecting' | 'connected' | 'disconnected'

/** Avatar endpoints that answered 404 are cached so bubbles fall back to initials without spamming 404s. */
const missingAvatars = new Set<string>()

/**
 * One chat's state, refreshed by its own event socket: the server sends `changed` after every stored message,
 * turn step and send, and the page reads the state and the open turns again.
 */
export function useChat(source: ChatSource) {
  const client = useQueryClient()
  const state = useQuery({
    queryKey: keys.chat.state(source.id),
    queryFn: ({ signal }) => chatApi.state(source, signal),
  })
  const live = ref<LiveStatus>('connecting')
  const avatarUrl = chatApi.avatar(source)
  const botAvatar = ref<string | null>(null)
  let avatarController: AbortController | null = null
  let avatarObjectUrl: string | null = null
  let socket: WebSocket | null = null
  let retry = 0
  let timer = 0
  let refreshTimer = 0
  let lastRefresh = 0
  const REFRESH_INTERVAL_MS = 300

  async function loadAvatar() {
    if (missingAvatars.has(avatarUrl)) {
      botAvatar.value = null
      return
    }
    avatarController = new AbortController()
    try {
      const response = await fetch(avatarUrl, {
        credentials: 'same-origin',
        signal: avatarController.signal,
      })
      if (response.status === 404) {
        missingAvatars.add(avatarUrl)
        botAvatar.value = null
        return
      }
      if (!response.ok) return
      const blob = await response.blob()
      if (avatarController.signal.aborted) return
      avatarObjectUrl = URL.createObjectURL(blob)
      botAvatar.value = avatarObjectUrl
    } catch {
      // Aborted or offline: stay on the initial fallback without marking the avatar missing.
    }
  }

  function runRefresh() {
    lastRefresh = Date.now()
    void client.invalidateQueries({ queryKey: keys.chat.all(source.id) })
  }
  function refresh(immediate = false) {
    if (immediate) {
      window.clearTimeout(refreshTimer)
      refreshTimer = 0
      runRefresh()
      return
    }
    const wait = lastRefresh + REFRESH_INTERVAL_MS - Date.now()
    if (wait <= 0) {
      window.clearTimeout(refreshTimer)
      refreshTimer = 0
      runRefresh()
    } else if (!refreshTimer) {
      refreshTimer = window.setTimeout(() => {
        refreshTimer = 0
        runRefresh()
      }, wait)
    }
  }
  function connect() {
    window.clearTimeout(timer)
    const connection = new WebSocket(chatApi.events(source))
    socket = connection
    live.value = 'connecting'
    connection.onopen = () => {
      if (socket !== connection) return
      live.value = 'connected'
      retry = 0
      refresh(true)
    }
    connection.onmessage = () => {
      if (socket === connection) refresh()
    }
    connection.onclose = () => {
      if (socket !== connection) return
      live.value = 'disconnected'
      // A dropped socket comes back on its own, slower each time; a stopped trial simply stays quiet.
      timer = window.setTimeout(connect, Math.min(30_000, 1000 * 2 ** retry++))
    }
  }
  function reconnect() {
    retry = 0
    const old = socket
    socket = null
    old?.close()
    connect()
  }
  onMounted(() => {
    connect()
    void loadAvatar()
  })
  onBeforeUnmount(() => {
    window.clearTimeout(timer)
    window.clearTimeout(refreshTimer)
    refreshTimer = 0
    const old = socket
    socket = null
    old?.close()
    avatarController?.abort()
    avatarController = null
    if (avatarObjectUrl) {
      URL.revokeObjectURL(avatarObjectUrl)
      avatarObjectUrl = null
    }
  })

  const data = computed(() => state.data.value)
  const isPrivate = computed(() => isPrivateScene(data.value?.scene ?? ''))
  const messages = computed(() => [...(data.value?.messages ?? [])].sort((a, b) => a.seq - b.seq))
  const turns = computed(() => [...(data.value?.turns ?? [])].sort((a, b) => b.started - a.started))
  const thinking = computed(() => turns.value.some((turn) => turn.ended === null))
  const botName = computed(() => data.value?.persona?.name ?? 'Bot')
  return { state, data, live, reconnect, isPrivate, messages, turns, thinking, botName, botAvatar }
}
export type Chat = ReturnType<typeof useChat>
