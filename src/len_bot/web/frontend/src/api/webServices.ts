/** Web search and read services, matching `SEARCH_APIS` and `READ_APIS` in models/providers.py. */

export type SearchService = 'yahoo' | 'bing_rss' | 'deepseek' | 'tavily' | 'brave' | 'bocha'
export type ReadService = 'local' | 'deepseek' | 'tavily' | 'jina'

/** Provider APIs a service accepts as its connection; services missing here need none. */
export const SEARCH_APIS: Partial<Record<SearchService, string[]>> = {
  deepseek: ['openai-chat', 'openai-responses', 'deepseek-search'],
  tavily: ['tavily'],
  brave: ['brave-search'],
  bocha: ['bocha'],
}
export const READ_APIS: Partial<Record<ReadService, string[]>> = {
  deepseek: ['openai-chat', 'openai-responses', 'deepseek-search'],
  tavily: ['tavily'],
  jina: ['jina-reader'],
}

/** The provider API and address a new connection of each paid service starts with. */
export const SERVICE_PROVIDER: Record<
  'deepseek' | 'tavily' | 'brave' | 'bocha' | 'jina',
  { api: string; url: string }
> = {
  deepseek: { api: 'deepseek-search', url: 'https://api.deepseek.com/v1' },
  tavily: { api: 'tavily', url: 'https://api.tavily.com' },
  brave: { api: 'brave-search', url: 'https://api.search.brave.com/res/v1' },
  bocha: { api: 'bocha', url: 'https://api.bochaai.com/v1' },
  jina: { api: 'jina-reader', url: 'https://r.jina.ai' },
}

export const SEARCH_SERVICES: SearchService[] = ['deepseek', 'tavily', 'brave', 'bocha', 'yahoo', 'bing_rss']
export const READ_SERVICES: ReadService[] = ['local', 'deepseek', 'tavily', 'jina']
