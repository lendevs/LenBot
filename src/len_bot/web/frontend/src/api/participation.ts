/** Fixed `attention.activity` values behind the three participation frequencies. */
export const ACTIVITY_LEVELS = { low: 0.2, medium: 0.3, high: 0.5 } as const
export type ActivityLevel = keyof typeof ACTIVITY_LEVELS

/** The level a stored activity value matches, or null for a value set by hand. */
export function activityLevel(activity: number): ActivityLevel | null {
  const entry = Object.entries(ACTIVITY_LEVELS).find(([, value]) => Math.abs(value - activity) < 1e-9)
  return entry ? (entry[0] as ActivityLevel) : null
}

export interface Participation {
  only_direct: boolean
  activity: number
}
