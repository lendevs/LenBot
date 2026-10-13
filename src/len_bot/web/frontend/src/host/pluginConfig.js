import { clone } from './forms.js'

export function initialField(field, value = field.default) {
  if (field.type === 'secret') return ''
  if (value == null) {
    if (field.type === 'boolean') return false
    if (field.type === 'scene') return null
    if (field.type === 'scene_list' || field.type === 'string_list') return []
    if (field.type === 'object_list') return field.fields.length ? [] : '[]'
    return ''
  }
  if (field.type === 'object_list') {
    return field.fields.length
      ? value.map(row => Object.fromEntries(field.fields.map(child => [child.key, initialField(child, row[child.key])])))
      : JSON.stringify(value, null, 2)
  }
  return clone(value)
}

// Short controls share a row in the form grid; text that tends to run long gets the full width.
export const wideField = field => ['url', 'path', 'string_list', 'scene_list', 'object_list'].includes(field.type)
  || (field.type === 'string' && field.multiline)

// One line for a collapsed object-list row: a name, its numbers, and short badges.
export function rowSummary(fields, row, sceneName) {
  let title = ''
  const meta = [], badges = []
  for (const child of fields) {
    const value = row[child.key], label = child.label || child.key
    if (child.options) {
      const option = child.options.find(item => item.value === value)
      if (option) badges.push(option.label)
    } else if (child.type === 'boolean') {
      if (value) badges.push(label)
    } else if (child.type === 'scene_list') {
      badges.push(value.length === 1 ? sceneName(value[0]) : `${value.length} 个群`)
    } else if (child.type === 'scene') {
      if (value) badges.push(sceneName(value))
    } else if (child.type === 'string_list') {
      if (value.length) meta.push(`${label} ${value.length} 项`)
    } else if (value !== '' && value !== null && value !== undefined) {
      const text = String(value).split('\n')[0]
      if (!title && child.type === 'string') title = text
      else meta.push(`${label} ${text}`)
    }
  }
  // Without a filled text field, the first number names the row.
  if (!title && meta.length) title = meta.shift()
  return { title, meta: meta.join(' · '), badges }
}

export function configValue(field, value) {
  if (field.type === 'object_list') {
    if (field.fields.length) return value.map(row => Object.fromEntries(field.fields
      .map(child => [child.key, configValue(child, row[child.key])])
      .filter(([, item]) => item !== undefined)))
    let items
    try { items = JSON.parse(value) } catch (error) { throw new Error(`${field.label || field.key} 不是合法的 JSON：${error.message}`) }
    if (!Array.isArray(items) || items.some(item => item === null || typeof item !== 'object' || Array.isArray(item))) {
      throw new Error(`${field.label || field.key} 必须是 JSON 对象列表`)
    }
    return items
  }
  if (field.type === 'string_list') return value.map(item => item.trim()).filter(Boolean)
  if (field.type === 'integer' || field.type === 'number') return value === '' || value === null ? undefined : Number(value)
  if (field.type === 'scene') return value ?? undefined
  return value
}

// What the host would reject for a field: a missing required number, group, path or address, or a number out of range.
function fieldProblem(field, value) {
  const label = field.label || field.key
  // Keep a space between a Latin-ending name and the Chinese that follows, e.g. 主播 UID 还没有填写.
  const name = /[A-Za-z0-9)]$/.test(label) ? `${label} ` : label
  if (['integer', 'number'].includes(field.type)) {
    if (value === '' || value === null) return field.required ? `${name}还没有填写` : ''
    if (field.minimum !== null && Number(value) < field.minimum) return `${name}不能小于 ${field.minimum}`
    if (field.maximum !== null && Number(value) > field.maximum) return `${name}不能大于 ${field.maximum}`
    if (field.type === 'integer' && !Number.isInteger(Number(value))) return `${name}必须是整数`
  }
  if (field.required && field.type === 'scene' && !value) return `${name}还没有选择`
  if (field.required && ['url', 'path'].includes(field.type) && value === '') return `${name}还没有填写`
  return ''
}

export function formProblem(fields, values) {
  for (const field of fields) {
    if (field.type === 'object_list' && field.fields.length) {
      for (const [index, row] of values[field.key].entries()) {
        for (const child of field.fields) {
          const problem = fieldProblem(child, row[child.key])
          if (problem) return `${field.label || field.key}第 ${index + 1} 项：${problem}`
        }
      }
    } else {
      const problem = fieldProblem(field, values[field.key])
      if (problem) return problem
    }
  }
  return ''
}
