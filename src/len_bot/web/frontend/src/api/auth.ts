import { http } from './client'

export type PanelMode = 'isolated' | 'isolated-multi'

export interface PanelContext {
  mode: PanelMode
  home: string
}

export interface PanelUser {
  username: string
  is_default_password: boolean
  /** Unix seconds of the last successful login since the panel started. */
  last_login_at?: number | null
}

export const authApi = {
  context: () => http.get<PanelContext>('/api/panel-context'),
  me: () => http.get<PanelUser>('/api/auth/me'),
  login: (username: string, password: string) =>
    http.post<PanelUser>('/api/auth/login', { username, password }),
  logout: () => http.post<void>('/api/auth/logout'),
}
