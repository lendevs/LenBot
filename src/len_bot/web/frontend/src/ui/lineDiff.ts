export interface DiffLine {
  kind: 'same' | 'add' | 'del'
  text: string
  oldLine: number | null
  newLine: number | null
}

/**
 * Myers O((M + N) * D) line diff after trimming identical prefix/suffix lines.
 * Preserves unchanged interior spans even on multi-hundred- or multi-thousand-line files.
 */
export function computeLineDiff(a: readonly string[], b: readonly string[]): DiffLine[] {
  let start = 0
  while (start < a.length && start < b.length && a[start] === b[start]) start += 1
  let endA = a.length
  let endB = b.length
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA -= 1
    endB -= 1
  }

  const lines: DiffLine[] = []
  for (let i = 0; i < start; i++) {
    lines.push({ kind: 'same', text: a[i]!, oldLine: i + 1, newLine: i + 1 })
  }

  const midA = a.slice(start, endA)
  const midB = b.slice(start, endB)
  const m = midA.length
  const n = midB.length

  if (m === 0) {
    for (let j = 0; j < n; j++) {
      lines.push({ kind: 'add', text: midB[j]!, oldLine: null, newLine: start + j + 1 })
    }
  } else if (n === 0) {
    for (let i = 0; i < m; i++) {
      lines.push({ kind: 'del', text: midA[i]!, oldLine: start + i + 1, newLine: null })
    }
  } else {
    const max = m + n
    const maxD = Math.min(max, 3000)
    const offset = max
    const v = new Int32Array(2 * max + 1)
    const trace: Int32Array[] = []
    let reached = -1

    for (let d = 0; d <= maxD; d++) {
      const snap = new Int32Array(2 * d + 1)
      for (let k = -d; k <= d; k++) snap[k + d] = v[offset + k]!
      trace.push(snap)

      for (let k = -d; k <= d; k += 2) {
        let x: number
        if (k === -d || (k !== d && v[offset + k - 1]! < v[offset + k + 1]!)) {
          x = v[offset + k + 1]!
        } else {
          x = v[offset + k - 1]! + 1
        }
        let y = x - k
        while (x < m && y < n && midA[x] === midB[y]) {
          x += 1
          y += 1
        }
        v[offset + k] = x
        if (x >= m && y >= n) {
          reached = d
          break
        }
      }
      if (reached !== -1) break
    }

    if (reached !== -1) {
      const ops: ('same' | 'add' | 'del')[] = []
      let x = m
      let y = n
      for (let d = reached; d > 0; d--) {
        const snap = trace[d]!
        const k = x - y
        const down = k === -d || (k !== d && snap[k - 1 + d]! < snap[k + 1 + d]!)
        const prevK = down ? k + 1 : k - 1
        const prevX = snap[prevK + d]!
        const prevY = prevX - prevK
        while (x > prevX && y > prevY) {
          x -= 1
          y -= 1
          ops.push('same')
        }
        if (down) {
          y -= 1
          ops.push('add')
        } else {
          x -= 1
          ops.push('del')
        }
      }
      while (x > 0 && y > 0) {
        x -= 1
        y -= 1
        ops.push('same')
      }
      ops.reverse()

      let idxA = 0
      let idxB = 0
      for (const op of ops) {
        if (op === 'same') {
          lines.push({
            kind: 'same',
            text: midA[idxA]!,
            oldLine: start + idxA + 1,
            newLine: start + idxB + 1,
          })
          idxA += 1
          idxB += 1
        } else if (op === 'del') {
          lines.push({
            kind: 'del',
            text: midA[idxA]!,
            oldLine: start + idxA + 1,
            newLine: null,
          })
          idxA += 1
        } else {
          lines.push({
            kind: 'add',
            text: midB[idxB]!,
            oldLine: null,
            newLine: start + idxB + 1,
          })
          idxB += 1
        }
      }
    } else {
      for (let i = 0; i < m; i++) {
        lines.push({ kind: 'del', text: midA[i]!, oldLine: start + i + 1, newLine: null })
      }
      for (let j = 0; j < n; j++) {
        lines.push({ kind: 'add', text: midB[j]!, oldLine: null, newLine: start + j + 1 })
      }
    }
  }

  for (let k = 0; k < a.length - endA; k++) {
    lines.push({ kind: 'same', text: a[endA + k]!, oldLine: endA + k + 1, newLine: endB + k + 1 })
  }
  return lines
}
