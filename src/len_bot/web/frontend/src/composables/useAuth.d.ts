// Types of the login state (useAuth.js) for TypeScript callers.
import type { PanelContext, PanelUser } from '../api/auth'

export interface AuthState {
  /** `setup`: the first-run wizard, which has no login. */
  status: 'loading' | 'authenticated' | 'unauthenticated' | 'error' | 'setup'
  user: PanelUser | null
  error: string
  panelContext: PanelContext | null
}

export function useAuth(): AuthState
export function clearAuth(): void
export function refreshAuth(): Promise<void>
export function ensureAuth(): Promise<void>
export function login(username: string, password: string): Promise<boolean>
export function logout(): Promise<void>
