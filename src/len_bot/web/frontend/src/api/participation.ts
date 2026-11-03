export type WakeLevel = 'active' | 'moderate' | 'quiet'

/** The attention fields each wake level sets; the same values as `WAKE_LEVELS` in `configuration/chat.py`. */
export const WAKE_LEVELS = {
  active: {
    activity: 0.3,
    ambient_min_interval_seconds: 60,
    ambient_max_interval_seconds: 900,
    focus_seconds: 180,
    focus_unanswered_limit: 2,
    explore_probability: 0,
  },
  moderate: {
    activity: 0.15,
    ambient_min_interval_seconds: 180,
    ambient_max_interval_seconds: 1800,
    focus_seconds: 90,
    focus_unanswered_limit: 1,
    explore_probability: 0,
  },
  quiet: {
    activity: 0.06,
    ambient_min_interval_seconds: 600,
    ambient_max_interval_seconds: 3600,
    focus_seconds: 30,
    focus_unanswered_limit: 1,
    explore_probability: 0,
  },
} as const satisfies Record<WakeLevel, Record<string, number>>

export const WAKE_LEVEL_ORDER = ['active', 'moderate', 'quiet'] as const satisfies readonly WakeLevel[]

export type WakeLevelFields = { [key in keyof (typeof WAKE_LEVELS)['active']]: number }

/** The level the attention fields match, or null for values set by hand. */
export function wakeLevelOf(attention: WakeLevelFields): WakeLevel | null {
  return (
    WAKE_LEVEL_ORDER.find((level) =>
      Object.entries(WAKE_LEVELS[level]).every(
        ([key, value]) => attention[key as keyof WakeLevelFields] === value,
      ),
    ) ?? null
  )
}

/** Answer calls only, or also join in at a level; a null level keeps the other attention fields. */
export interface Participation {
  only_direct: boolean
  level: WakeLevel | null
}

export const DEFAULT_PARTICIPATION: Participation = { only_direct: true, level: 'moderate' }
