// 个人书籍预测数据处理纯逻辑测试：段落偏移映射 / 长难句定位 / 片段切分（不做生词高亮）
import { describe, expect, it } from 'vitest'
import {
  buildSegments,
  locateSentence,
  mapParagraphs,
  normalizeWord,
} from '../src/utils/personalPrediction'
import type { PredictedSentence } from '../src/types'

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

describe('buildSegments（仅长难句切片，无生词高亮）', () => {
  it('句子片段带标记，前后普通文本合并且无标记', () => {
    const segs = buildSegments('Before text. The long sentence here. After text.', [{ start: 13, end: 36 }])
    expect(segs).toEqual([
      { text: 'Before text. ' },
      { text: 'The long sentence here.', sentence: true },
      { text: ' After text.' },
    ])
  })

  it('多个长难句正确切分', () => {
    const segs = buildSegments('One. Two. Three.', [{ start: 0, end: 4 }, { start: 5, end: 9 }])
    expect(segs).toEqual([
      { text: 'One.', sentence: true },
      { text: ' ' },
      { text: 'Two.', sentence: true },
      { text: ' Three.' },
    ])
  })

  it('无长难句时整段作为单一片段', () => {
    expect(buildSegments('Plain text.', [])).toEqual([{ text: 'Plain text.' }])
  })

  it('范围越界被收敛且不破坏文本拼接', () => {
    const segs = buildSegments('Hello world.', [{ start: -5, end: 100 }])
    expect(segs.map(s => s.text).join('')).toBe('Hello world.')
    expect(segs[0].sentence).toBe(true)
  })
})
