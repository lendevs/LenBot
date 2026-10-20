import type { ConfigField, FieldValue, SavedValue } from '../../../api/plugins'

/** A form value: text, a number or null while empty, a switch, a list, or an object list's rows. */
export type DraftValue = string | number | boolean | null | string[] | Row[]
export type Row = Record<string, DraftValue>
export type Draft = Record<string, DraftValue>
type Translate = (key: string, named?: Record<string, unknown>) => string

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
export const fieldLabel = (field: ConfigField) => field.label || field.key
/** An object list with declared sub-fields is edited row by row; one without is edited as JSON. */
export const hasRows = (field: ConfigField) => field.type === 'object_list' && field.fields.length > 0

export function initialField(field: ConfigField, value: FieldValue = field.default): DraftValue {
  if (field.type === 'secret') return ''
  if (value === null || value === undefined) {
    if (field.type === 'boolean') return false
    if (field.type === 'integer' || field.type === 'number' || field.type === 'scene') return null
    if (field.type === 'scene_list' || field.type === 'string_list') return []
    if (field.type === 'object_list') return hasRows(field) ? [] : '[]'
    return ''
  }
  if (field.type === 'object_list') {
    const rows = value as Record<string, FieldValue>[]
    return hasRows(field)
      ? rows.map((row) =>
          Object.fromEntries(field.fields.map((child) => [child.key, initialField(child, row[child.key])])),
        )
      : JSON.stringify(value, null, 2)
  }
  return clone(value) as DraftValue
}

export function initialDraft(fields: ConfigField[], saved: Record<string, SavedValue> | undefined): Draft {
  return Object.fromEntries(
    fields.map((field) => {
      const item = saved?.[field.key]
      return [field.key, initialField(field, item && 'value' in item ? item.value : field.default)]
    }),
  )
}

/** Short controls share a row of the form; text that tends to run long takes the whole row. */
export const wideField = (field: ConfigField) =>
  ['url', 'path', 'string_list', 'scene_list', 'object_list'].includes(field.type) ||
  (field.type === 'string' && field.multiline)

/** A few short choices read better as a segmented control than as a dropdown. */
export const segmented = (field: ConfigField) =>
  Boolean(
    field.options &&
    field.options.length <= 3 &&
    field.options.every((option) => [...option.label].length <= 8),
  )

/** The range shown inside a number box; a lone lower bound of 0 or 1 only says the number is not negative. */
export function rangeText(field: ConfigField): string | undefined {
  const { minimum: low, maximum: high } = field
  if (low !== null && high !== null) return `${low}–${high}`
  if (low !== null) return low > 1 ? `≥ ${low}` : undefined
  return high !== null ? `≤ ${high}` : undefined
}

/** A collapsed object-list row: the first filled text names it, numbers and other text follow, choices are badges. */
export function rowSummary(fields: ConfigField[], row: Row, group: (scene: string) => string, t: Translate) {
  let title = ''
  const meta: string[] = []
  const badges: string[] = []
  for (const child of fields) {
    const value = row[child.key]
    const label = fieldLabel(child)
    if (child.options) {
      const option = child.options.find((item) => item.value === value)
      if (option) badges.push(option.label)
    } else if (child.type === 'boolean') {
      if (value) badges.push(label)
    } else if (child.type === 'scene_list') {
      const scenes = value as string[]
      if (scenes.length)
        badges.push(scenes.length === 1 ? group(scenes[0]) : t('plugins.form.groups', { n: scenes.length }))
    } else if (child.type === 'scene') {
      if (value) badges.push(group(value as string))
    } else if (child.type === 'string_list') {
      const items = value as string[]
      if (items.length) meta.push(t('plugins.form.items', { label, n: items.length }))
    } else if (value !== '' && value !== null && value !== undefined) {
      const text = String(value).split('\n')[0]
      if (!title && child.type === 'string') title = text
      else meta.push(`${label} ${text}`)
    }
  }
  // Without filled text, the first number names the row.
  if (!title && meta.length) title = meta.shift()!
  return { title, meta: meta.join(' · '), badges }
}

/** What the host stores for one field; undefined leaves it out so the plugin's default applies. */
export function configValue(field: ConfigField, value: DraftValue, t: Translate): FieldValue | undefined {
  if (field.type === 'object_list') {
    if (hasRows(field)) {
      return (value as Row[]).map((row) =>
        Object.fromEntries(
          field.fields
            .map((child) => [child.key, configValue(child, row[child.key], t)] as const)
            .filter(([, item]) => item !== undefined),
        ),
      ) as FieldValue
    }
    let items: unknown
    try {
      items = JSON.parse(value as string)
    } catch (error) {
      throw new Error(t('plugins.form.badJson', { name: fieldLabel(field), error: (error as Error).message }))
    }
    if (
      !Array.isArray(items) ||
      items.some((item) => item === null || typeof item !== 'object' || Array.isArray(item))
    )
      throw new Error(t('plugins.form.notObjects', { name: fieldLabel(field) }))
    return items as FieldValue
  }
  if (field.type === 'string_list') return (value as string[]).map((item) => item.trim()).filter(Boolean)
  if (field.type === 'integer' || field.type === 'number' || field.type === 'scene') return value ?? undefined
  return value as FieldValue
}

function fieldProblem(field: ConfigField, value: DraftValue, t: Translate): string | null {
  const name = fieldLabel(field)
  if (field.type === 'integer' || field.type === 'number') {
    if (value === null) return field.required ? t('plugins.form.missing', { name }) : null
    const number = value as number
    if (field.minimum !== null && number < field.minimum)
      return t('plugins.form.below', { name, n: field.minimum })
    if (field.maximum !== null && number > field.maximum)
      return t('plugins.form.above', { name, n: field.maximum })
    if (field.type === 'integer' && !Number.isInteger(number)) return t('plugins.form.integer', { name })
  }
  if (field.required && field.type === 'scene' && !value) return t('plugins.form.pick', { name })
  if (field.required && (field.type === 'url' || field.type === 'path') && value === '')
    return t('plugins.form.missing', { name })
  if (field.type === 'object_list' && !hasRows(field)) {
    try {
      configValue(field, value, t)
    } catch (error) {
      return (error as Error).message
    }
  }
  return null
}

/**
 * What the host would refuse, keyed by field (`key`, or `key.row.child` inside an object list).
 * An empty secret keeps its saved value, so it only counts as missing when none was saved.
 */
export function formProblems(
  fields: ConfigField[],
  values: Draft,
  configured: Record<string, boolean>,
  t: Translate,
): Record<string, string> {
  const problems: Record<string, string> = {}
  for (const field of fields) {
    if (field.type === 'secret') {
      if (field.required && !configured[field.key] && values[field.key] === '')
        problems[field.key] = t('plugins.form.missing', { name: fieldLabel(field) })
      continue
    }
    if (hasRows(field)) {
      ;(values[field.key] as Row[]).forEach((row, index) => {
        for (const child of field.fields) {
          const problem = fieldProblem(child, row[child.key], t)
          if (problem) problems[`${field.key}.${index}.${child.key}`] = problem
        }
      })
    } else {
      const problem = fieldProblem(field, values[field.key], t)
      if (problem) problems[field.key] = problem
    }
  }
  return problems
}

/** The body of PUT /api/host/plugins/{name}: an empty secret that was saved before is sent as null to keep it. */
export function configBody(
  fields: ConfigField[],
  values: Draft,
  saved: Record<string, SavedValue> | undefined,
  t: Translate,
): Record<string, FieldValue> {
  const config: Record<string, FieldValue> = {}
  for (const field of fields) {
    const value = values[field.key]
    if (field.type === 'secret') {
      const kept = saved?.[field.key]
      if (value !== '') config[field.key] = value as string
      else if (kept && 'configured' in kept && kept.configured) config[field.key] = null
    } else {
      const parsed = configValue(field, value, t)
      if (parsed !== undefined) config[field.key] = parsed
    }
  }
  return config
}
