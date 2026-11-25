/**
 * Minimal YAML frontmatter `tags` parser and serializer matching `persona/knowledge.py`.
 * Preserves all non-`tags` frontmatter keys and untouched body bytes.
 */

interface FrontmatterSpan {
  /** Line ending used in the document (`\n` or `\r\n`). */
  eol: string
  /** Lines inside the frontmatter (excluding the `---` fence lines). */
  headerLines: string[]
  /** Remaining document text starting right after the closing `---` line. */
  body: string
}

function splitFrontmatter(content: string): { span: FrontmatterSpan | null; unclosed: boolean } {
  const eol = content.includes('\r\n') ? '\r\n' : '\n'
  const lines = content.match(/[^\r\n]*(?:\r?\n|$)/g) ?? []
  if (lines.length && lines[lines.length - 1] === '') lines.pop()
  if (!lines.length || lines[0]!.replace(/\r?\n$/, '') !== '---') {
    return { span: null, unclosed: false }
  }
  let closing = -1
  for (let i = 1; i < lines.length; i++) {
    if (lines[i]!.replace(/\r?\n$/, '') === '---') {
      closing = i
      break
    }
  }
  if (closing === -1) return { span: null, unclosed: true }
  return {
    span: {
      eol,
      headerLines: lines.slice(1, closing).map((line) => line.replace(/\r?\n$/, '')),
      body: lines.slice(closing + 1).join(''),
    },
    unclosed: false,
  }
}

function unquoteYamlScalar(raw: string): string {
  const trimmed = raw.trim()
  if (trimmed.length >= 2 && trimmed.startsWith('"') && trimmed.endsWith('"')) {
    try {
      const parsed: unknown = JSON.parse(trimmed)
      if (typeof parsed === 'string') return parsed
    } catch {
      // Fall through to strip outer quotes.
    }
    return trimmed.slice(1, -1)
  }
  if (trimmed.length >= 2 && trimmed.startsWith("'") && trimmed.endsWith("'")) {
    return trimmed.slice(1, -1).replace(/''/g, "'")
  }
  return trimmed
}

function parseFlowSequence(raw: string): string[] {
  const inner = raw.trim().slice(1, -1)
  const result: string[] = []
  let current = ''
  let quote: '"' | "'" | null = null
  for (let i = 0; i < inner.length; i++) {
    const ch = inner[i]!
    if (quote) {
      current += ch
      if (quote === '"' && ch === '\\' && i + 1 < inner.length) {
        current += inner[++i]!
      } else if (quote === "'" && ch === "'" && inner[i + 1] === "'") {
        current += inner[++i]!
      } else if (ch === quote) {
        quote = null
      }
      continue
    }
    if (ch === '"' || ch === "'") {
      quote = ch
      current += ch
    } else if (ch === ',') {
      const value = unquoteYamlScalar(current)
      if (value) result.push(value)
      current = ''
    } else {
      current += ch
    }
  }
  const tail = unquoteYamlScalar(current)
  if (tail) result.push(tail)
  return result
}

function findTagsRange(headerLines: string[]): { start: number; end: number; inline: string } | null {
  for (let i = 0; i < headerLines.length; i++) {
    const match = headerLines[i]!.match(/^tags\s*:(.*)$/)
    if (!match) continue
    const inline = match[1]!.trim()
    let end = i + 1
    if (!inline) {
      while (end < headerLines.length) {
        const line = headerLines[end]!
        if (line.trim() === '' || /^\s*#/.test(line) || /^\s*-\s+/.test(line) || /^\s+/.test(line)) {
          end += 1
        } else {
          break
        }
      }
    }
    return { start: i, end, inline }
  }
  return null
}

/** YAML-safe string scalar; quotes anything `yaml.safe_load` might not parse back as the exact same string. */
function formatYamlString(value: string): string {
  if (
    !value ||
    /^\s|\s$/.test(value) ||
    /^(?:true|false|yes|no|on|off|null|~|[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|0x[0-9a-fA-F]+|0o[0-7]+|\.inf|-\.inf|\.nan)$/i.test(
      value,
    ) ||
    /[:#[\]{},&*!|>'"%@`?\\]|^-\s|^-$|\r|\n/.test(value)
  ) {
    return JSON.stringify(value)
  }
  return value
}

/** Extract string tags from Markdown YAML frontmatter; returns empty when absent or unclosed. */
export function parseFrontmatterTags(content: string): string[] {
  const { span } = splitFrontmatter(content)
  if (!span) return []
  const range = findTagsRange(span.headerLines)
  if (!range) return []
  if (range.inline) {
    if (range.inline.startsWith('[') && range.inline.endsWith(']')) {
      return parseFlowSequence(range.inline)
    }
    return []
  }
  const tags: string[] = []
  for (let i = range.start + 1; i < range.end; i++) {
    const match = span.headerLines[i]!.match(/^\s*-\s+(.*)$/)
    if (!match) continue
    const value = unquoteYamlScalar(match[1]!)
    if (value) tags.push(value)
  }
  return tags
}

/** Whether the document begins with `---` without a closing `---` fence. */
export function hasUnclosedFrontmatter(content: string): boolean {
  return splitFrontmatter(content).unclosed
}

/** Update or insert YAML frontmatter `tags` while keeping other frontmatter keys and body intact. */
export function syncFrontmatterTags(content: string, tags: string[]): string {
  const clean = [...new Set(tags.map((item) => item.trim()).filter(Boolean))]
  const { span, unclosed } = splitFrontmatter(content)
  if (unclosed) return content

  const tagBlock = clean.length ? ['tags:', ...clean.map((tag) => `  - ${formatYamlString(tag)}`)] : []

  if (!span) {
    if (!clean.length) return content
    const eol = content.includes('\r\n') ? '\r\n' : '\n'
    const header = ['---', ...tagBlock, '---'].join(eol)
    if (!content) return `${header}${eol}`
    return `${header}${eol}${eol}${content}`
  }

  const nextHeader = [...span.headerLines]
  const range = findTagsRange(nextHeader)
  if (range) {
    nextHeader.splice(range.start, range.end - range.start, ...tagBlock)
  } else if (tagBlock.length) {
    nextHeader.push(...tagBlock)
  }

  const hasContent = nextHeader.some((line) => line.trim() !== '')
  if (!hasContent) {
    return span.body.replace(/^\r?\n/, '')
  }
  const header = ['---', ...nextHeader, '---'].join(span.eol)
  return span.body ? `${header}${span.eol}${span.body}` : `${header}${span.eol}`
}
