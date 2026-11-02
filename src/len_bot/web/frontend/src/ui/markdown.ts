/**
 * A Markdown subset for model-written text and release notes: headings, lists, rules, tables, code blocks,
 * `code`, **bold** and [links](https://…). Links other than http(s) stay text.
 */

export type Span =
  | { kind: 'text' | 'code'; text: string }
  | { kind: 'link'; text: string; href: string }
  | { kind: 'strong'; children: Span[] }
export type Item = { depth: number; marker: string; spans: Span[] }
export type Block =
  | { kind: 'heading'; spans: Span[] }
  | { kind: 'paragraph'; lines: Span[][] }
  | { kind: 'code'; text: string }
  | { kind: 'rule' }
  | { kind: 'list'; items: Item[] }
  | { kind: 'table'; head: Span[][]; rows: Span[][][] }

const CODE = /(`[^`]+`)/
const STRONG = /(\*\*[^*]+\*\*)/
const HEADING = /^#{1,6}\s+(.*)$/
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/
const LIST = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/
const LINK = /(\[[^\]]+\]\(https?:\/\/[^)\s]+\))/
const ROW = /^\s*\|.*\|\s*$/
const DIVIDER = /^\s*\|?(\s*:?-{3,}:?\s*\|)+(\s*:?-{3,}:?\s*)?\|?\s*$/

function linkSpans(text: string): Span[] {
  return text
    .split(LINK)
    .filter(Boolean)
    .map((part): Span => {
      const link = /^\[([^\]]+)\]\((\S+)\)$/.exec(part)
      return link ? { kind: 'link', text: link[1]!, href: link[2]! } : { kind: 'text', text: part }
    })
}

function cells(line: string): Span[][] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => spans(cell.trim()))
}

function codeSpans(text: string): Span[] {
  return text
    .split(CODE)
    .filter(Boolean)
    .flatMap((part) =>
      part.length > 2 && part.startsWith('`') && part.endsWith('`')
        ? [{ kind: 'code' as const, text: part.slice(1, -1) }]
        : linkSpans(part),
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
    if (ROW.test(line) && DIVIDER.test(lines[index + 1] ?? '')) {
      const rows: Span[][][] = []
      for (index += 2; index < lines.length && ROW.test(lines[index]!); index++)
        rows.push(cells(lines[index]!))
      index--
      result.push({ kind: 'table', head: cells(line), rows })
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
