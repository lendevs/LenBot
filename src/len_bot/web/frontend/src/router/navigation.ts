/** `value` when it is a path inside this panel other than the login page, else an empty string. */
export function internalPath(value: unknown): string {
  const unsafe = /[\\\u0000- ]/
  if (typeof value !== 'string' || !value.startsWith('/') || unsafe.test(value)) return ''
  const path = value.split(/[?#]/, 1)[0]
  let decoded: string
  try {
    decoded = decodeURIComponent(path)
  } catch {
    return ''
  }
  if (decoded.startsWith('//') || unsafe.test(decoded) || /^\/login(?:\/|$)/.test(decoded)) return ''
  const url = new URL(value, 'https://panel.invalid')
  if (url.origin !== 'https://panel.invalid' || /^\/login(?:\/|$)/.test(url.pathname)) return ''
  return value
}
