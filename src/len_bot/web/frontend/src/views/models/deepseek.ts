export const DEEPSEEK_RECOMMENDED_EFFORT = 'high' as const

const SUBOPTIMAL_EFFORTS = new Set(['none', 'off', 'minimal', 'low', 'medium'])
const DISABLED_EFFORTS = new Set(['none', 'off'])

export interface DeepSeekTuningState {
  antiBagu: boolean
  effort?: string | null
  quickEffort?: string | null
  thinking?: 'enabled' | 'disabled' | null
}

export interface ReasoningExpectationInput {
  thinking?: 'enabled' | 'disabled' | null
  effort?: string | null
  thinkingBudget?: number | null
}

/** True when DeepSeek's reasoning settings will degrade chat into zero/low-thinking clichés. */
export function needsDeepSeekThinkingTune(state: DeepSeekTuningState): boolean {
  if (state.thinking === 'disabled') return true
  const quick = state.quickEffort?.trim().toLowerCase() ?? ''
  if (quick !== '') return true
  const main = state.effort?.trim().toLowerCase() ?? ''
  return main === '' || SUBOPTIMAL_EFFORTS.has(main)
}

export function isDeepSeekFullyTuned(state: DeepSeekTuningState): boolean {
  return state.antiBagu && !needsDeepSeekThinkingTune(state)
}

/** Effort preserved on tune when already at least `high`, otherwise `'high'`. */
export function tunedDeepSeekEffort(current: string | null | undefined): string {
  const main = current?.trim() ?? ''
  if (!main || SUBOPTIMAL_EFFORTS.has(main.toLowerCase())) return DEEPSEEK_RECOMMENDED_EFFORT
  return main
}

/** True when the binding explicitly asks the model to think, so a zero-reasoning probe warrants a warning. */
export function expectsReasoning(state: ReasoningExpectationInput): boolean {
  if (state.thinking === 'disabled') return false
  if (state.thinking === 'enabled') return true
  if (state.thinkingBudget != null && state.thinkingBudget > 0) return true
  const main = state.effort?.trim().toLowerCase() ?? ''
  return main !== '' && !DISABLED_EFFORTS.has(main)
}
