import { reactive } from 'vue'
import { resetSession } from '../api/client'
import { authApi } from '../api/auth'
import { queryClient } from '../api/query'
import { startStream, stopStream } from '../realtime/stream'
import { clearHost } from '../host/store.js'

const state = reactive({ status: 'loading', user: null, error: '', panelContext: null })
let initialization
let authRequest = 0
const homes = { isolated: '/chat-test', 'isolated-multi': '/overview' }

export function useAuth() {
  return state
}

/** Everything cached for the previous user goes: requests in flight, query cache, old store, event stream. */
function forgetSession() {
  resetSession()
  stopStream()
  queryClient.clear()
  clearHost()
}

function authenticated(user) {
  state.user = user
  state.status = 'authenticated'
  state.error = ''
  if (state.panelContext?.mode === 'isolated-multi') startStream()
}

export function clearAuth() {
  ++authRequest
  forgetSession()
  state.user = null
  state.status = 'unauthenticated'
  state.error = ''
}

export async function refreshAuth() {
  const own = ++authRequest
  state.status = 'loading'
  state.error = ''
  try {
    if (!state.panelContext) {
      const context = await authApi.context()
      if (own !== authRequest) return
      if (!Object.hasOwn(homes, context.mode) || context.home !== homes[context.mode]) {
        throw new Error(`面板环境响应无效：mode 或 home 不符合当前面板契约：${JSON.stringify(context)}`)
      }
      state.panelContext = context
    }
    const user = await authApi.me()
    if (own !== authRequest) return
    authenticated(user)
  } catch (error) {
    if (own !== authRequest) return
    if (error.status === 401) clearAuth()
    else {
      state.status = 'error'
      state.error = error.message
    }
  }
}

export function ensureAuth() {
  if (!initialization) initialization = refreshAuth()
  return initialization
}

export async function login(username, password) {
  const own = ++authRequest
  const result = await authApi.login(username, password)
  if (own !== authRequest) return false
  forgetSession()
  authenticated(result)
  return true
}

export async function logout() {
  await authApi.logout()
  clearAuth()
}
