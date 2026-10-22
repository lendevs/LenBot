import { computed, inject, reactive, ref, watch, type InjectionKey } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Protocol } from '../../api/models'
import type {
  FirstSetup,
  OneBotLink,
  SetupBinding,
  SetupEmbedding,
  SetupModel,
  SetupProvider,
} from '../../api/setup'

/** Draft, checks and request bodies of the first-run wizard; one instance per page, shared by the steps. */

export const steps = ['account', 'platform', 'owner', 'model', 'persona'] as const
export type Step = (typeof steps)[number]
type Section = Step | 'vectors'

export interface Draft {
  username: string
  password: string
  passwordAgain: string
  port: number | null
  transport: 'forward_ws' | 'reverse_ws'
  wsUrl: string
  listenHost: string
  listenPort: number | null
  accessToken: string
  onebotTimeout: number | null
  delivery: 'simulated' | 'onebot'
  owner: string
  timezone: string
  preset: 'deepseek' | 'compatible' | 'other'
  search: 'off' | 'yahoo' | 'deepseek'
  searchConnection: 'primary' | 'separate'
  searchBaseUrl: string
  searchKey: string
  searchProxy: string
  readWeb: boolean
  quickEffort: string
  imageInput: boolean
  maxSteps: number | null
  api: string
  baseUrl: string
  apiKey: string
  proxy: string
  model: string
  contextWindow: number | null
  inputBudget: number | null
  maxOutput: number | null
  temperature: number | null
  effort: string
  thinkingBudget: number | null
  outputField: 'max_completion_tokens' | 'max_tokens'
  probeKind: 'text' | 'tools'
  vectorMode: 'skip' | 'primary' | 'separate'
  vectorBaseUrl: string
  vectorKey: string
  vectorProxy: string
  vectorModel: string
  vectorDimensions: number | null
  persona: 'companion' | 'custom'
  personaId: string
  personaName: string
  brief: string
  voice: string
  boundaries: string
  sceneKind: 'group' | 'private'
  sceneId: string
  plugins: string[]
}

const DRAFT_KEY = 'lenbot-setup-draft'
/** Not kept across reloads: they are typed again. */
const SECRETS = ['password', 'passwordAgain', 'accessToken', 'apiKey', 'vectorKey', 'searchKey'] as const

function initial(): Draft {
  return {
    username: '',
    password: '',
    passwordAgain: '',
    port: 8088,
    transport: 'forward_ws',
    wsUrl: '',
    listenHost: '127.0.0.1',
    listenPort: 8080,
    accessToken: '',
    onebotTimeout: 30,
    delivery: 'simulated',
    owner: '',
    timezone: 'Asia/Shanghai',
    preset: 'deepseek',
    search: 'deepseek',
    searchConnection: 'primary',
    searchBaseUrl: 'https://api.deepseek.com/v1',
    searchKey: '',
    searchProxy: '',
    readWeb: true,
    quickEffort: 'low',
    imageInput: true,
    maxSteps: 16,
    api: 'openai-chat',
    baseUrl: 'https://api.deepseek.com/v1',
    apiKey: '',
    proxy: '',
    model: 'deepseek-flash',
    contextWindow: 1000000,
    inputBudget: 6000,
    maxOutput: 8192,
    temperature: null,
    effort: 'high',
    thinkingBudget: null,
    outputField: 'max_tokens',
    probeKind: 'text',
    vectorMode: 'skip',
    vectorBaseUrl: '',
    vectorKey: '',
    vectorProxy: '',
    vectorModel: '',
    vectorDimensions: null,
    persona: 'companion',
    personaId: 'my-bot',
    personaName: '',
    brief: '',
    voice: '',
    boundaries: '',
    sceneKind: 'group',
    sceneId: '',
    plugins: [],
  }
}

function restored(): Draft {
  const draft = initial()
  try {
    const saved = JSON.parse(sessionStorage.getItem(DRAFT_KEY) ?? '{}') as Partial<Draft>
    for (const key of Object.keys(draft) as (keyof Draft)[]) {
      if (key in saved && !(SECRETS as readonly string[]).includes(key)) {
        ;(draft as unknown as Record<string, unknown>)[key] = saved[key]
      }
    }
  } catch {
    // No usable draft: start empty.
  }
  return draft
}

const ACCOUNT = /^[1-9][0-9]*$/
const PERSONA_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/

function httpUrl(text: string): boolean {
  try {
    const url = new URL(text)
    return ['http:', 'https:'].includes(url.protocol) && Boolean(url.host)
  } catch {
    return false
  }
}

function wsUrl(text: string): boolean {
  try {
    const url = new URL(text)
    return ['ws:', 'wss:'].includes(url.protocol) && Boolean(url.host)
  } catch {
    return false
  }
}

const trimUrl = (text: string) => text.trim().replace(/\/+$/, '')

/** Problems of one step, keyed by field, as i18n keys under `setup.problems`. */
export type Problems = Partial<Record<string, string>>

export function createWizard() {
  const draft = reactive(restored())
  const protocols = ref<Protocol[]>([])
  const container = ref(false)
  const catalog = ref<SetupModel[]>([])
  const vectorCatalog = ref<SetupModel[]>([])

  /** What a connection or model test passed with; a later edit makes it stale. */
  const platform = ref<{ signature: string; botId: string } | null>(null)
  const modelPassed = ref<string | null>(null)
  let keep = true

  watch(
    draft,
    (value) => {
      if (!keep) return
      const kept: Partial<Draft> = { ...value }
      for (const key of SECRETS) delete kept[key]
      try {
        sessionStorage.setItem(DRAFT_KEY, JSON.stringify(kept))
      } catch {
        // Storage refused: the draft lasts until the page is closed.
      }
    },
    { deep: true },
  )

  function onebot(): OneBotLink {
    const common = { access_token: draft.accessToken, request_timeout_seconds: draft.onebotTimeout ?? 30 }
    return draft.transport === 'forward_ws'
      ? { mode: 'forward_ws', ws_url: draft.wsUrl.trim(), ...common }
      : {
          mode: 'reverse_ws',
          listen_host: draft.listenHost.trim(),
          listen_port: draft.listenPort ?? 0,
          ...common,
        }
  }

  function provider(): SetupProvider {
    return {
      api: draft.api,
      base_url: trimUrl(draft.baseUrl),
      api_key: draft.apiKey,
      proxy: trimUrl(draft.proxy) || null,
    }
  }

  function binding(): SetupBinding {
    return {
      provider: 'primary',
      model: draft.model.trim(),
      context_window_tokens: draft.contextWindow ?? 0,
      max_output_tokens: draft.maxOutput ?? 0,
      temperature: draft.temperature,
      quick_reasoning_effort: draft.quickEffort.trim() || null,
      image_input: draft.imageInput,
      reasoning_effort: draft.effort.trim() || null,
      thinking_budget_tokens: draft.thinkingBudget,
      output_token_field: draft.api === 'openai-chat' ? draft.outputField : 'max_completion_tokens',
    }
  }

  /** Only an OpenAI-compatible chat provider also serves embeddings. */
  const chatServesVectors = computed(() => draft.api === 'openai-chat')

  function vectorProvider(): SetupProvider {
    return draft.vectorMode === 'primary'
      ? provider()
      : {
          api: 'openai-embeddings',
          base_url: trimUrl(draft.vectorBaseUrl),
          api_key: draft.vectorKey,
          proxy: trimUrl(draft.vectorProxy) || null,
        }
  }

  function vectorBinding(): SetupEmbedding {
    return {
      provider: draft.vectorMode === 'primary' ? 'primary' : 'vectors',
      model: draft.vectorModel.trim(),
      dimensions: draft.vectorDimensions,
    }
  }

  const platformSignature = computed(() => JSON.stringify(onebot()))
  const modelSignature = computed(() => JSON.stringify([provider(), binding(), draft.probeKind]))
  const platformReady = computed(() => platform.value?.signature === platformSignature.value)
  const modelReady = computed(() => modelPassed.value === modelSignature.value)

  function choosePreset(preset: Draft['preset']) {
    draft.preset = preset
    Object.assign(draft, {
      apiKey: '',
      proxy: '',
      thinkingBudget: null,
      temperature: null,
      api: 'openai-chat',
      baseUrl: '',
      model: '',
      contextWindow: 128000,
      maxOutput: 8192,
      effort: '',
      quickEffort: '',
      outputField: 'max_completion_tokens',
      imageInput: false,
      search: 'yahoo',
      searchConnection: 'separate',
    })
    if (preset === 'deepseek')
      Object.assign(draft, {
        baseUrl: 'https://api.deepseek.com/v1',
        model: 'deepseek-flash',
        contextWindow: 1000000,
        effort: 'high',
        quickEffort: 'low',
        outputField: 'max_tokens',
        imageInput: true,
        search: 'deepseek',
        searchConnection: 'primary',
      })
    catalog.value = []
  }

  function chooseProtocol(api: string) {
    const protocol = protocols.value.find((item) => item.api === api)
    draft.api = api
    draft.baseUrl = protocol?.base_url ?? ''
    // Native protocols all take an effort level and images; a compatible service may take neither.
    const native = api !== 'openai-chat'
    Object.assign(draft, {
      effort: native ? 'high' : '',
      quickEffort: native ? 'low' : '',
      thinkingBudget: null,
      temperature: null,
      imageInput: native,
      outputField: 'max_completion_tokens',
    })
    catalog.value = []
    if (api !== 'openai-chat' && draft.vectorMode === 'primary') draft.vectorMode = 'separate'
  }

  /** Called once the protocols are read: keeps a restored choice, or takes the first protocol. */
  function settleProtocol() {
    if (!protocols.value.some((item) => item.api === draft.api) && protocols.value[0]) {
      chooseProtocol(protocols.value[0].api)
    }
  }

  // Leaves room for the reply: three quarters of what the window keeps after the output.
  watch(
    () => [draft.contextWindow, draft.maxOutput] as const,
    ([window, output], previous) => {
      if (!previous || window === null || output === null) return
      if (window > output + 1024) draft.inputBudget = Math.floor((window - output) * 0.75)
    },
  )

  function problems(step: Section): Problems {
    const found: Problems = {}
    const need = (field: string, ok: boolean, key = 'required') => {
      if (!ok && !found[field]) found[field] = key
    }
    if (step === 'account') {
      need('username', Boolean(draft.username.trim()))
      need('username', draft.username === draft.username.trim(), 'spaces')
      need('password', draft.password.length >= 8, 'passwordShort')
      need('password', Boolean(draft.password.trim()), 'passwordBlank')
      need('passwordAgain', draft.password === draft.passwordAgain, 'passwordMismatch')
      need('port', draft.port !== null && draft.port >= 1 && draft.port <= 65535, 'port')
    }
    if (step === 'platform') {
      if (draft.transport === 'forward_ws') need('wsUrl', wsUrl(draft.wsUrl.trim()), 'wsUrl')
      else {
        need('listenHost', Boolean(draft.listenHost.trim()))
        need(
          'listenPort',
          draft.listenPort !== null && draft.listenPort >= 1 && draft.listenPort <= 65535,
          'port',
        )
      }
      need('onebotTimeout', draft.onebotTimeout !== null && draft.onebotTimeout >= 1, 'required')
      if (!Object.keys(found).length) need('connect', platformReady.value, 'connectFirst')
    }
    if (step === 'owner') {
      need('owner', ACCOUNT.test(draft.owner.trim()), 'account')
      need('timezone', Boolean(draft.timezone.trim()))
    }
    if (step === 'model') {
      need('api', Boolean(draft.api))
      need('baseUrl', httpUrl(draft.baseUrl.trim()), 'httpUrl')
      need('apiKey', Boolean(draft.apiKey))
      if (draft.proxy.trim()) need('proxy', httpUrl(draft.proxy.trim()), 'httpUrl')
      need('model', Boolean(draft.model.trim()))
      need('contextWindow', draft.contextWindow !== null && draft.contextWindow >= 2048, 'contextWindow')
      need('maxOutput', draft.maxOutput !== null && draft.maxOutput >= 1)
      need('inputBudget', draft.inputBudget !== null && draft.inputBudget >= 1)
      need('thinkingBudget', !(draft.effort.trim() && draft.thinkingBudget !== null), 'bothThinking')
      need('maxSteps', draft.maxSteps !== null && draft.maxSteps > 0)
      if (draft.search === 'deepseek' && draft.searchConnection === 'separate') {
        need('searchBaseUrl', httpUrl(draft.searchBaseUrl.trim()), 'httpUrl')
        need('searchKey', Boolean(draft.searchKey.trim()))
        if (draft.searchProxy.trim()) need('searchProxy', httpUrl(draft.searchProxy.trim()), 'httpUrl')
      }
      if (draft.search === 'deepseek' && draft.searchConnection === 'primary')
        need('searchConnection', ['openai-chat', 'openai-responses'].includes(draft.api), 'searchConnection')
      Object.assign(found, problems('vectors'))
    }
    if (step === 'vectors' && draft.vectorMode !== 'skip') {
      if (draft.vectorMode === 'separate') {
        need('vectorBaseUrl', httpUrl(draft.vectorBaseUrl.trim()), 'httpUrl')
        need('vectorKey', Boolean(draft.vectorKey))
        if (draft.vectorProxy.trim()) need('vectorProxy', httpUrl(draft.vectorProxy.trim()), 'httpUrl')
      }
      need('vectorModel', Boolean(draft.vectorModel.trim()))
    }
    if (step === 'persona') {
      if (draft.persona === 'custom') {
        need('personaId', PERSONA_ID.test(draft.personaId), 'personaId')
        need('personaName', Boolean(draft.personaName.trim()))
        need('brief', Boolean(draft.brief.trim()))
      }
      need('sceneId', ACCOUNT.test(draft.sceneId.trim()), 'account')
    }
    return found
  }

  /** Steps whose problems are shown: the ones the operator tried to leave. */
  const tried = reactive(new Set<Section>())
  const shown = (step: Section): Problems =>
    tried.has(step) || (step === 'vectors' && tried.has('model')) ? problems(step) : {}

  function body(): FirstSetup {
    const persona =
      draft.persona === 'companion'
        ? { persona_id: 'companion' }
        : {
            persona_id: draft.personaId,
            persona_name: draft.personaName.trim(),
            brief: draft.brief.trim(),
            ...(draft.voice.trim() ? { voice_text: draft.voice.trim() } : {}),
            boundaries: draft.boundaries.trim(),
          }
    return {
      bot_id: platform.value?.botId ?? '',
      owners: [`onebot:${draft.owner.trim()}`],
      timezone: draft.timezone.trim(),
      delivery: draft.delivery,
      onebot: onebot(),
      provider: provider(),
      mind: binding(),
      embedding:
        draft.vectorMode === 'skip'
          ? null
          : {
              provider: draft.vectorMode === 'primary' ? null : vectorProvider(),
              model: vectorBinding().model,
              dimensions: draft.vectorDimensions,
            },
      web_search:
        draft.search === 'off'
          ? null
          : {
              provider: draft.search,
              connection:
                draft.search === 'deepseek'
                  ? draft.searchConnection === 'primary'
                    ? 'primary'
                    : 'search'
                  : null,
              timeout_seconds: 15,
              max_results: 5,
            },
      search_provider:
        draft.search === 'deepseek' && draft.searchConnection === 'separate'
          ? {
              api: 'deepseek-search',
              base_url: trimUrl(draft.searchBaseUrl),
              api_key: draft.searchKey,
              proxy: trimUrl(draft.searchProxy) || null,
            }
          : null,
      web_read: draft.readWeb,
      max_steps: draft.maxSteps ?? 16,
      voice_mode: 'direct',
      compaction: { input_tokens: draft.inputBudget ?? 0 },
      scene: `onebot:${draft.sceneKind}:${draft.sceneId.trim()}`,
      ...persona,
      panel_port: draft.port ?? 0,
      username: draft.username,
      password: draft.password,
      password_confirmation: draft.passwordAgain,
      install_plugins: [...draft.plugins],
    }
  }

  /** After saving: the draft and the secrets are gone from this tab. */
  function clear() {
    keep = false
    Object.assign(draft, initial())
    try {
      sessionStorage.removeItem(DRAFT_KEY)
    } catch {
      // Nothing stored.
    }
  }

  return {
    draft,
    protocols,
    container,
    catalog,
    vectorCatalog,
    platform,
    modelPassed,
    platformReady,
    modelReady,
    platformSignature,
    modelSignature,
    chatServesVectors,
    onebot,
    provider,
    binding,
    vectorProvider,
    vectorBinding,
    choosePreset,
    chooseProtocol,
    settleProtocol,
    problems,
    tried,
    shown,
    body,
    clear,
  }
}

export type Wizard = ReturnType<typeof createWizard>
export const wizardKey: InjectionKey<Wizard> = Symbol('setup-wizard')

export function useWizard(): Wizard {
  const wizard = inject(wizardKey)
  if (!wizard) throw new Error('useWizard() needs the setup page')
  return wizard
}

/** The translated problem of one field in a step, once the step was tried. */
export function useStepErrors(step: Section) {
  const wizard = useWizard()
  const { t } = useI18n()
  const current = computed(() => wizard.shown(step))
  return (field: string): string | null => {
    const key = current.value[field]
    return key ? t(`setup.problems.${key}`) : null
  }
}
