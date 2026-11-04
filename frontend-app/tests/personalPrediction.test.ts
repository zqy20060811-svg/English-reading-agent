// 个人书籍预测数据处理纯逻辑测试：段落偏移映射 / 生词匹配 / 长难句定位 / 片段切分
import { describe, expect, it } from 'vitest'
import {
  buildSegments,
  locateSentence,
  mapParagraphs,
  normalizeWord,
  wordMapOf,
} from '../src/utils/personalPrediction'
import type { PredictedSentence, PredictedWord } from '../src/types'

function word(w: string, count = 1, inVocab = false): PredictedWord {
  return { word: w, level: 'B2', count, in_vocabulary: inVocab }
}

function sentence(text: string, charStart: number | null, index = 1): PredictedSentence {
  return { sentence_index: index, char_start: charStart, word_count: 10, clause_markers: 2, text }
}

describe('normalizeWord', () => {
  it('小写并去掉尾部撇号（与后端 normalize_token 口径一致）', () => {
    expect(normalizeWord("Fox'")).toBe('fox')
    expect(normalizeWord('Rabbit’')).toBe('rabbit') // 尾部弯引号
    expect(normalizeWord("Dog's")).toBe("dog's") // 所有格中间的撇号保留（与后端一致）
    expect(normalizeWord('  Hello  ')).toBe('hello')
  })
})

describe('mapParagraphs', () => {
  it('与阅读器相同的切分规则，并记录原文偏移', () => {
    const content = 'First para here.\n\nSecond para.\n\n \n\nThird.'
    const paras = mapParagraphs(content)
    expect(paras.map(p => p.text)).toEqual(['First para here.', 'Second para.', 'Third.'])
    expect(paras.map(p => p.start)).toEqual([0, 18, 35])
  })

  it('段首带空白时 trimStart 偏移正确', () => {
    const content = 'A.\n\n   Indented para.'
    const paras = mapParagraphs(content)
    expect(paras[1].text).toBe('Indented para.')
    expect(paras[1].trimStart).toBe(3)
    expect(paras[1].start).toBe(4)
  })

  it('空内容返回空数组', () => {
    expect(mapParagraphs('')).toEqual([])
    expect(mapParagraphs('\n\n  \n\n')).toEqual([])
  })
})

describe('locateSentence', () => {
  const content = 'Short one.\n\nHe told me that although the plan which had been approved by the committee was flawed, nobody objected.\n\nLast para.'
  const paras = mapParagraphs(content)
  const long = paras[1].text

  it('char_start 精确映射到所在段落', () => {
    const charStart = content.indexOf(long)
    const r = locateSentence(paras, sentence(long, charStart))
    expect(r!.paraIndex).toBe(1)
    expect(r!.range.start).toBe(0)
    expect(r!.range.end).toBe(long.length)
  })

  it('char_start 对不上时回退按句子原文定位', () => {
    const r = locateSentence(paras, sentence(long, 999999))
    expect(r!.paraIndex).toBe(1)
    expect(paras[1].text.slice(r!.range.start, r!.range.end)).toBe(long)
  })

  it('char_start 为 null 时按原文定位', () => {
    const r = locateSentence(paras, sentence(long, null))
    expect(r!.paraIndex).toBe(1)
  })

  it('定位失败返回 null，不影响正文', () => {
    expect(locateSentence(paras, sentence('Not present in the text at all.', null))).toBeNull()
  })
})

describe('buildSegments', () => {
  it('同一单词多次出现全部命中', () => {
    const words = wordMapOf([word('rabbit', 3)])
    const segs = buildSegments('The rabbit ran. Another rabbit slept.', words, [])
    const marked = segs.filter(s => s.word)
    expect(marked).toHaveLength(2)
    expect(marked.every(s => s.word!.word === 'rabbit')).toBe(true)
    expect(segs.map(s => s.text).join('')).toBe('The rabbit ran. Another rabbit slept.')
  })

  it('所有格与大小写归一化后命中', () => {
    const words = wordMapOf([word('wonder')])
    const segs = buildSegments('The Wonder was strange.', words, [])
    expect(segs.filter(s => s.word).map(s => s.text)).toEqual(['Wonder'])
  })

  it('生词嵌套在长难句内时同时带两个标记', () => {
    const words = wordMapOf([word('committee')])
    const text = 'The plan which the committee approved was flawed.'
    const segs = buildSegments(text, words, [{ start: 0, end: text.length }])
    const hit = segs.find(s => s.word)!
    expect(hit.sentence).toBe(true)
    expect(hit.word!.word).toBe('committee')
    expect(segs.map(s => s.text).join('')).toBe(text)
  })

  it('普通文本片段合并且不产生标记', () => {
    const words = wordMapOf([word('fox')])
    const segs = buildSegments('A quick brown fox.', words, [])
    expect(segs).toEqual([
      { text: 'A quick brown ' },
      { text: 'fox', word: words.get('fox'), sentence: undefined },
      { text: '.' },
    ])
  })

  it('无生词无长难句时整段作为单一片段', () => {
    expect(buildSegments('Plain text.', wordMapOf([]), [])).toEqual([{ text: 'Plain text.' }])
  })
})
