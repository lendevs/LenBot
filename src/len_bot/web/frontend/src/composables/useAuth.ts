import { reactive } from 'vue'
import { ApiError, resetSession } from '../api/client'
import { authApi, type PanelContext, type PanelMode, type PanelUser } from '../api/auth'
import { queryClient } from '../api/query'
import { clearHost } from '../api/hostStore'
import { startStream, stopStream } from '../realtime/stream'
import { i18n } from '../i18n'

export interface AuthState {
  /** `setup`: the first-run wizard, which has no login. */
  status: 'loading' | 'authenticated' | 'unauthenticated' | 'error' | 'setup'
  user: PanelUser | null
  error: string
  panelContext: PanelContext | null
}

const state = reactive<AuthState>({ status: 'loading', user: null, error: '', panelContext: null })
let initialization: Promise<void> | undefined
let authRequest = 0
const homes: Record<PanelMode, string> = {
  isolated: '/chat-test',
  'isolated-multi': '/overview',
  setup: '/setup',
}

export function useAuth(): AuthState {
  return state
}

/** Everything cached for the previous user goes: requests in flight, query cache, host store, event stream. */
function forgetSession() {
  resetSession()
  stopStream()
  queryClient.clear()
  clearHost()
}

function authenticated(user: PanelUser) {
  state.user = user
  state.status = 'authenticated'
  state.error = ''
  if (state.panelContext?.mode === 'isolated-multi') startStream()
}

export function clearAuth(): void {
  ++authRequest
  forgetSession()
  state.user = null
  state.status = 'unauthenticated'
  state.error = ''
}

export async function refreshAuth(): Promise<void> {
  const own = ++authRequest
  state.status = 'loading'
  state.error = ''
  try {
    if (!state.panelContext) {
      const context = await authApi.context()
      if (own !== authRequest) return
      if (!Object.hasOwn(homes, context.mode) || context.home !== homes[context.mode]) {
        throw new Error(i18n.global.t('login.badContext', { context: JSON.stringify(context) }))
      }
      state.panelContext = context
    }
    // The wizard has no accounts yet; it authorizes each request with the startup token instead.
    if (state.panelContext.mode === 'setup') {
      state.status = 'setup'
      return
    }
    const user = await authApi.me()
    if (own !== authRequest) return
    authenticated(user)
  } catch (error) {
    if (own !== authRequest) return
    if (error instanceof ApiError && error.status === 401) clearAuth()
    else {
      state.status = 'error'
      state.error = error instanceof Error ? error.message : String(error)
    }
  }
}

export function ensureAuth(): Promise<void> {
  if (!initialization) initialization = refreshAuth()
  return initialization
}

export async function login(username: string, password: string): Promise<boolean> {
  const own = ++authRequest
  const result = await authApi.login(username, password)
  if (own !== authRequest) return false
  forgetSession()
  authenticated(result)
  return true
}

export async function logout(): Promise<void> {
  await authApi.logout()
  clearAuth()
}
