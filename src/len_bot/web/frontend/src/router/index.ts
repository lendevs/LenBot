import {
  createRouter,
  createWebHashHistory,
  type LocationQuery,
  type RouteLocationNormalized,
  type RouteRecordRaw,
} from 'vue-router'
import { ensureAuth, useAuth, clearAuth } from '../composables/useAuth.js'
import { setUnauthorizedHandler } from '../api.js'
import { i18n } from '../i18n'
import { areaOf } from '../layouts/nav'
import { internalPath } from './navigation.js'
import { groupsTarget, type GroupTab } from '../views/groups/route'

type SceneRule = boolean | ((route: RouteLocationNormalized) => boolean)

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    /** Rendered without the shell (development gallery). */
    bare?: boolean
    /** i18n key of the document title when the page is not a sidebar entry. */
    titleKey?: string
    /** Old pages: whether HostPage shows the group switcher. */
    scene?: SceneRule
    sceneSwitch?: boolean
    sceneMode?: 'scene' | 'role'
  }
}

const page = (
  path: string,
  name: string,
  component: RouteRecordRaw['component'],
  meta: RouteRecordRaw['meta'] = {},
) => ({ path, name, component, meta }) as RouteRecordRaw

/** Host pages. Route names other than `groups` are the ones old pages link to. */
const hostRoutes: RouteRecordRaw[] = [
  page('/overview', 'host-overview', () => import('../views/overview/OverviewView.vue')),
  page('/playground', 'host-trials', () => import('../host/pages/trial/TrialPage.vue')),
  page('/groups/:scene?/:tab?', 'groups', () => import('../views/groups/GroupsView.vue')),
  page('/personas', 'host-persona', () => import('../views/personas/PersonasView.vue')),
  page('/plugins', 'host-plugins', () => import('../views/plugins/PluginsView.vue')),
  page('/capabilities', 'host-capabilities', () => import('../views/capabilities/CapabilitiesView.vue')),
  page('/models', 'host-models', () => import('../views/models/ModelsView.vue')),
  page('/system', 'host-system', () => import('../views/system/SystemView.vue')),
  page('/system/logs', 'host-logs', () => import('../host/pages/logs/LogsPage.vue'), {
    scene: (route) => route.query.tab !== 'system',
  }),
]

const trialRoutes: RouteRecordRaw[] = [
  page('/chat-test/settings', 'chat-test-settings', () => import('../views/ChatTestSettingsView.vue'), {
    titleKey: 'shell.pages.playground',
  }),
  page('/chat-test', 'chat-test', () => import('../views/ChatTestView.vue'), {
    titleKey: 'shell.pages.playground',
  }),
]

/** Addresses of the old shell, still used by bookmarks and the documentation site. */
const moved: Record<string, string> = {
  overview: '/overview',
  'chat-test': '/playground',
  persona: '/personas',
  plugins: '/plugins',
  capabilities: '/capabilities',
  models: '/models',
  system: '/system',
  logs: '/system/logs',
}

/** Old group pages, by name and by their `/host/...` address; they now open a tab of the workbench. */
const sceneTabs: Record<string, GroupTab> = {
  messages: 'live',
  settings: 'settings',
  permissions: 'settings',
  brain: 'session',
  learning: 'learning',
}
function legacyGroup(
  path: string,
  name: string,
  target: (query: LocationQuery) => [GroupTab, LocationQuery],
): RouteRecordRaw {
  return {
    path,
    name,
    redirect: (to) => {
      const { scene, ...rest } = to.query
      const [tab, query] = target(rest)
      return groupsTarget(typeof scene === 'string' ? scene : undefined, tab, query)
    },
  }
}
const legacyGroupRoutes = [
  legacyGroup('/host/scenes', 'host-scenes', ({ tab, ...query }) => [
    sceneTabs[String(tab)] ?? 'live',
    query,
  ]),
  legacyGroup('/host/memory', 'host-memory', (query) => ['memory', query]),
  legacyGroup('/host/tasks', 'host-tasks', (query) => ['tasks', query]),
  legacyGroup('/host/resources', 'host-resources', ({ task, ...query }) => [
    'tasks',
    { ...query, tab: 'resources', ...(task ? { id: task } : {}) },
  ]),
]

const hostPageNames = hostRoutes.map((route) => route.name)
const trialPageNames = trialRoutes.map((route) => route.name)

/** A safe in-app path to return to after login; anything else goes to the mode's home. */
export function returnPath(value: unknown): string {
  const context = useAuth().panelContext
  if (!context) return '/overview'
  const path = internalPath(value)
  const pages = context.mode === 'isolated' ? trialPageNames : hostPageNames
  return path && pages.includes(router.resolve(path).name ?? '') ? path : context.home
}

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: { name: 'host-overview' } },
    ...hostRoutes,
    ...trialRoutes,
    ...legacyGroupRoutes,
    {
      path: '/host/:page(.*)',
      redirect: (to) => ({ path: moved[String(to.params.page)] ?? '/overview', query: to.query }),
    },
    page('/login', 'login', () => import('../views/LoginView.vue'), {
      public: true,
      titleKey: 'shell.pages.login',
    }),
    page('/:pathMatch(.*)*', 'not-found', () => import('../views/NotFoundView.vue'), {
      titleKey: 'shell.pages.notFound',
    }),
  ],
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.name === from.name && (to.query.id !== from.query.id || to.query.result !== from.query.result))
      return false
    return { top: 0 }
  },
})

// Component gallery for development only; the dynamic import is dropped from production builds.
if (import.meta.env.DEV) {
  router.addRoute(
    page('/dev/ui', 'dev-ui', () => import('../dev/UiGallery.vue'), { public: true, bare: true }),
  )
}

router.beforeEach(async (to) => {
  await ensureAuth()
  const auth = useAuth()
  if (auth.status === 'error' || !auth.panelContext) return true
  const pages = auth.panelContext.mode === 'isolated' ? trialPageNames : hostPageNames
  if (!to.meta.public && auth.status !== 'authenticated') {
    return { name: 'login', query: { redirect: returnPath(to.fullPath) } }
  }
  if (to.name === 'login' && auth.status === 'authenticated') return returnPath(to.query.redirect)
  if (!to.meta.public && to.name !== 'not-found' && !pages.includes(to.name)) return auth.panelContext.home
})

export function pageTitle(route: RouteLocationNormalized): string {
  const area = areaOf(route.name)
  const key =
    area?.pages.find((item) => item.route === route.name)?.label ?? area?.label ?? route.meta.titleKey
  return key ? i18n.global.t(key) : 'LenBot'
}

router.afterEach((to) => {
  document.title = `${pageTitle(to)} · LenBot`
})

setUnauthorizedHandler(() => {
  const wasAuthenticated = useAuth().status === 'authenticated'
  clearAuth()
  const current = router.currentRoute.value
  if (wasAuthenticated && current.name !== 'login') {
    router.replace({ name: 'login', query: { redirect: current.fullPath } })
  }
})

export default router
