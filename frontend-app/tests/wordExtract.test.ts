// extractWordAt 单元测试：点词定位与句子边界提取
import { describe, expect, it } from 'vitest'
import { extractWordAt } from '../src/utils/wordExtract'

// 构造一个只实现 caretRangeFromPoint 的假 document，返回指定文本节点与偏移
function fakeDoc(text: string, offset: number): Document {
  const node = document.createTextNode(text)
  return {
    caretRangeFromPoint: () => ({ startContainer: node, startOffset: offset }),
  } as unknown as Document
}

describe('extractWordAt', () => {
  const SENTENCE = 'Alice was beginning to get very tired of sitting by her sister on the bank. '

  it('提取坐标处的完整单词', () => {
    const offset = SENTENCE.indexOf('beginning') + 4 // 词中间
    const hit = extractWordAt(fakeDoc(SENTENCE, offset), 0, 0)
    expect(hit?.word).toBe('beginning')
  })

  it('连字符与撇号视为单词字符', () => {
    const text = "It's a well-known fact. "
    const hit = extractWordAt(fakeDoc(text, text.indexOf('known') + 2), 0, 0)
    expect(hit?.word).toBe('well-known')
    const hit2 = extractWordAt(fakeDoc(text, text.indexOf("'")), 0, 0)
    expect(hit2?.word).toBe("It's")
  })

  it('提取的句子以词所在句为界，不跨到下一句', () => {
    const text = 'The pool was full of tears. Alice swam in it. Then she dried off. '
    const hit = extractWordAt(fakeDoc(text, text.indexOf('swam') + 1), 0, 0)
    expect(hit?.sentence).toBe('Alice swam in it.')
  })

  it('句子边界含引号句点（." ）', () => {
    const text = '"Curiouser!" said Alice. She went on. '
    const hit = extractWordAt(fakeDoc(text, text.indexOf('said') + 1), 0, 0)
    expect(hit?.sentence).toBe('"Curiouser!" said Alice.')
  })

  it('点击标点 / 空白处返回 null', () => {
    const offset = SENTENCE.indexOf(' ') // 空格
    expect(extractWordAt(fakeDoc(SENTENCE, offset), 0, 0)).toBeNull()
    const commaOffset = 'Yes, sir. '.indexOf(',')
    expect(extractWordAt(fakeDoc('Yes, sir. ', commaOffset), 0, 0)).toBeNull()
  })

  it('偏移在文本末尾返回 null', () => {
    expect(extractWordAt(fakeDoc(SENTENCE, SENTENCE.length), 0, 0)).toBeNull()
  })

  it('单字符（长度 1）不作为生词返回', () => {
    const text = 'a cat sat. '
    const hit = extractWordAt(fakeDoc(text, 0), 0, 0)
    expect(hit).toBeNull()
  })
})
