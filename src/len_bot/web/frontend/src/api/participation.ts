export type WakeLevel = 'active' | 'moderate' | 'quiet'

/** The attention fields each wake level sets; the same values as `WAKE_LEVELS` in `configuration/chat.py`. */
export const WAKE_LEVELS = {
  active: {
    ambient_min_interval_seconds: 600,
    ambient_max_interval_seconds: 2400,
    speech_burst: 3,
    speech_interval_seconds: 120,
  },
  moderate: {
    ambient_min_interval_seconds: 1800,
    ambient_max_interval_seconds: 7200,
    speech_burst: 3,
    speech_interval_seconds: 180,
  },
  quiet: {
    ambient_min_interval_seconds: 5400,
    ambient_max_interval_seconds: 21600,
    speech_burst: 2,
    speech_interval_seconds: 300,
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

/** A group added from the panel or the setup wizard joins in at a wake level. */
export const NEW_GROUP_PARTICIPATION: Participation = { only_direct: false, level: 'moderate' }

/** Chat lets the model take part; plugins answers only plugins and commands. */
export type ChatMode = 'chat' | 'plugins'
