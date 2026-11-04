// 个人书籍预测辅助测试：词条归一化（正文无高亮，仅用于点词弹层命中预测生词表）
import { describe, expect, it } from 'vitest'
import { normalizeWord } from '../src/utils/personalPrediction'

describe('normalizeWord', () => {
  it('小写并去掉尾部撇号（与后端 normalize_token 口径一致）', () => {
    expect(normalizeWord("Fox'")).toBe('fox')
    expect(normalizeWord('Rabbit’')).toBe('rabbit') // 尾部弯引号
    expect(normalizeWord("Dog's")).toBe("dog's") // 所有格中间的撇号保留（与后端一致）
    expect(normalizeWord('  Hello  ')).toBe('hello')
  })
})
