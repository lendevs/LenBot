/** A Markdown subset for model-written text: headings, lists, rules, code blocks, `code` and **bold**. */

export type Span = { kind: 'text' | 'code'; text: string } | { kind: 'strong'; children: Span[] }
export type Item = { depth: number; marker: string; spans: Span[] }
export type Block =
  | { kind: 'heading'; spans: Span[] }
  | { kind: 'paragraph'; lines: Span[][] }
  | { kind: 'code'; text: string }
  | { kind: 'rule' }
  | { kind: 'list'; items: Item[] }

const CODE = /(`[^`]+`)/
const STRONG = /(\*\*[^*]+\*\*)/
const HEADING = /^#{1,6}\s+(.*)$/
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/
const LIST = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/

function codeSpans(text: string): Span[] {
  return text
    .split(CODE)
    .filter(Boolean)
    .map((part) =>
      part.length > 2 && part.startsWith('`') && part.endsWith('`')
        ? { kind: 'code', text: part.slice(1, -1) }
        : { kind: 'text', text: part },
    )
}

export function spans(text: string): Span[] {
  return text
    .split(STRONG)
    .filter(Boolean)
    .flatMap((part) =>
      part.length > 4 && part.startsWith('**') && part.endsWith('**')
        ? [{ kind: 'strong' as const, children: codeSpans(part.slice(2, -2)) }]
        : codeSpans(part),
    )
}

/** Blocks in order; a list keeps each item's indentation depth and its own marker text. */
export function blocks(text: string): Block[] {
  const result: Block[] = []
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  let blank = true
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index]!
    const last = result.at(-1)
    if (line.trimStart().startsWith('```')) {
      const body: string[] = []
      for (index++; index < lines.length && !lines[index]!.trimStart().startsWith('```'); index++)
        body.push(lines[index]!)
      result.push({ kind: 'code', text: body.join('\n') })
      blank = true
      continue
    }
    if (!line.trim()) {
      blank = true
      continue
    }
    const heading = HEADING.exec(line)
    const rule = RULE.test(line)
    const item = rule ? null : LIST.exec(line)
    if (heading) result.push({ kind: 'heading', spans: spans(heading[1]!) })
    else if (rule) result.push({ kind: 'rule' })
    else if (item) {
      const entry = {
        depth: Math.floor(item[1]!.replace(/\t/g, '  ').length / 2),
        marker: /\d/.test(item[2]!) ? item[2]! : '•',
        spans: spans(item[3]!),
      }
      if (last?.kind === 'list') last.items.push(entry)
      else result.push({ kind: 'list', items: [entry] })
    } else if (!blank && last?.kind === 'paragraph') last.lines.push(spans(line.trim()))
    else if (!blank && last?.kind === 'list')
      last.items.at(-1)!.spans.push({ kind: 'text', text: ' ' + line.trim() })
    else result.push({ kind: 'paragraph', lines: [spans(line.trim())] })
    blank = false
  }
  return result
}
