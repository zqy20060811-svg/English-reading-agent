// 个人书籍预测数据处理（阶段D）：把章节预测结果安全地映射到正文段落上
//
// 设计约束：
// - 正文是纯文本段落（ReaderView 按 \n\n 切分渲染），这里在「数据层」把段落文本
//   切成带标记的片段数组，由 Vue v-for 渲染 —— 不改渲染后的 DOM、不对 HTML 字符串
//   做正则替换，天然不会破坏段落结构与分页
// - 后端 char_start 是相对章节原文（content 全文）的偏移，本文件的 mapParagraphs
//   用与渲染完全相同的切分规则还原每段的起始偏移，保证映射精确
// - 长难句定位失败（偏移对不上、原文找不到）时静默跳过，绝不影响正文显示

import type { PredictedSentence, PredictedWord } from '../types'

// 与后端 text_statistics.tokenize 相同口径的切词正则
const WORD_RE = /[A-Za-z][A-Za-z'-]*/g

/** 词条归一化：与后端 cefr_lexicon.normalize_token 一致（小写 + 去尾部撇号） */
export function normalizeWord(token: string): string {
  let w = token.trim().toLowerCase()
  while (w && (w.endsWith("'") || w.endsWith('’'))) w = w.slice(0, -1)
  return w
}

export interface MappedParagraph {
  /** 段落在章节原文中的起始偏移（供长难句 char_start 映射） */
  start: number
  /** 段落原文（未 trim） */
  raw: string
  /** 展示文本（trim 后，与阅读器渲染一致） */
  text: string
  /** 展示文本相对原文的偏移（trim 掉的头部字符数） */
  trimStart: number
}

/** 按阅读器的规则（split /\n\s*\n/ 过滤空白段）切分段落并记录原文偏移 */
export function mapParagraphs(content: string): MappedParagraph[] {
  const out: MappedParagraph[] = []
  const sep = /\n\s*\n/
  let pos = 0
  for (;;) {
    const rest = content.slice(pos)
    const m = rest.match(sep)
    const raw = m ? rest.slice(0, m.index) : rest
    const trimmed = raw.trim()
    if (trimmed) {
      out.push({
        start: pos,
        raw,
        text: trimmed,
        trimStart: raw.length - raw.trimStart().length,
      })
    }
    if (!m) break
    pos += m.index! + m[0].length
  }
  return out
}

/** 生词查找表：归一化小写 → 预测条目 */
export function wordMapOf(words: PredictedWord[]): Map<string, PredictedWord> {
  return new Map(words.map(w => [w.word, w]))
}

/** 长难句在某一段中的局部范围（相对展示文本），null = 定位失败静默跳过 */
export interface SentenceRange {
  start: number
  end: number
}

/**
 * 定位长难句：优先 char_start（映射到所在段落后在段内检索句子原文），
 * 偏移对不上时回退为全书段落文本检索，再失败返回 null。
 */
export function locateSentence(
  paras: MappedParagraph[],
  sentence: PredictedSentence,
): { paraIndex: number; range: SentenceRange } | null {
  if (!sentence.text) return null

  const findInPara = (p: MappedParagraph, from: number): SentenceRange | null => {
    // 展示文本做了 trim，检索起点要补偿偏移
    let idx = p.text.indexOf(sentence.text, Math.max(0, from - p.trimStart))
    if (idx < 0) idx = p.text.indexOf(sentence.text)
    if (idx < 0) return null
    return { start: idx, end: idx + sentence.text.length }
  }

  // 1) char_start 映射：找到包含该偏移的段落
  if (sentence.char_start != null) {
    for (let i = paras.length - 1; i >= 0; i--) {
      const p = paras[i]
      if (sentence.char_start >= p.start) {
        const range = findInPara(p, sentence.char_start - p.start)
        if (range) return { paraIndex: i, range }
        break // 偏移落在这一段但句内检索失败 → 走全局回退
      }
    }
  }

  // 2) 回退：按句子原文逐段检索（后端分句不跨段落，句子必完整落在某一段内）
  for (let i = 0; i < paras.length; i++) {
    const range = findInPara(paras[i], 0)
    if (range) return { paraIndex: i, range }
  }
  return null
}

/** 渲染片段：text 为不可再分的文本；word/sentence 标记驱动高亮样式与点击行为 */
export interface ParaSegment {
  text: string
  word?: PredictedWord
  sentence?: boolean
}

/**
 * 把段落展示文本切成渲染片段：
 * - 先按生词与长难句的全部边界切分（两者可嵌套：句内的生词同时带两个标记）
 * - 相邻的普通文本合并，保持片段数最少
 */
export function buildSegments(
  text: string,
  words: Map<string, PredictedWord>,
  sentenceRanges: SentenceRange[],
): ParaSegment[] {
  if (!words.size && !sentenceRanges.length) return [{ text }]

  const wordHits: Array<{ start: number; end: number; word: PredictedWord }> = []
  const cuts = new Set<number>([0, text.length])
  for (const m of text.matchAll(WORD_RE)) {
    const w = words.get(normalizeWord(m[0]))
    if (!w) continue
    wordHits.push({ start: m.index!, end: m.index! + m[0].length, word: w })
    cuts.add(m.index!)
    cuts.add(m.index! + m[0].length)
  }
  const sents = sentenceRanges
    .map(r => ({ start: Math.max(0, r.start), end: Math.min(text.length, r.end) }))
    .filter(r => r.end > r.start)
  for (const r of sents) {
    cuts.add(r.start)
    cuts.add(r.end)
  }

  const points = [...cuts].sort((a, b) => a - b)
  const segs: ParaSegment[] = []
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i]
    const b = points[i + 1]
    if (b <= a) continue
    const piece = text.slice(a, b)
    const inSentence = sents.some(r => r.start <= a && b <= r.end)
    const hit = wordHits.find(w => w.start === a && w.end === b)
    if (!inSentence && !hit) {
      const last = segs[segs.length - 1]
      if (last && !last.word && !last.sentence) last.text += piece
      else segs.push({ text: piece })
    } else {
      segs.push({ text: piece, word: hit?.word, sentence: inSentence || undefined })
    }
  }
  return segs
}
