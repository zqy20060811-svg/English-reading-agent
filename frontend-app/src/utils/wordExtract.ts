// 点词查义的文本提取：定位点击处的英文单词与其所在句子（纯逻辑，便于单元测试）

export interface WordHit {
  word: string
  sentence: string
}

type CaretDoc = Document & {
  caretRangeFromPoint?: (x: number, y: number) => Range | null
  caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null
}

/** 在指定坐标处提取英文单词（含连字符/撇号）与所在句子，非文本节点或非单词处返回 null */
export function extractWordAt(doc: CaretDoc, x: number, y: number): WordHit | null {
  let node: Node | null = null
  let offset = 0
  if (doc.caretRangeFromPoint) {
    const r = doc.caretRangeFromPoint(x, y)
    node = r?.startContainer ?? null
    offset = r?.startOffset ?? 0
  } else if (doc.caretPositionFromPoint) {
    const p = doc.caretPositionFromPoint(x, y)
    node = p?.offsetNode ?? null
    offset = p?.offset ?? 0
  }
  if (!node || node.nodeType !== Node.TEXT_NODE) return null
  const text = node.textContent || ''
  if (offset >= text.length) return null
  const isWordChar = (ch: string): boolean => /[A-Za-z'-]/.test(ch)
  if (!isWordChar(text[offset])) return null
  let s = offset
  let e = offset
  while (s > 0 && isWordChar(text[s - 1])) s--
  while (e < text.length && isWordChar(text[e])) e++
  const word = text.slice(s, e)
  if (word.length < 2 || word.length > 40) return null
  // 句子边界：向前找句号/问号/叹号，向后找句末标点
  let ss = Math.max(text.lastIndexOf('. ', e), text.lastIndexOf('! ', e), text.lastIndexOf('? ', e), text.lastIndexOf('." ', e)) + 1
  if (ss >= e) ss = 0
  let se = text.length
  for (const mark of ['. ', '! ', '? ', '." ']) {
    const i = text.indexOf(mark, e)
    if (i !== -1 && i < se) se = i + mark.length
  }
  const sentence = text.slice(ss, se).trim().slice(0, 400)
  return { word, sentence }
}
