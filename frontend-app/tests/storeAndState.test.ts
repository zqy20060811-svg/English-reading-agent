// levelOf 等级分档与 StateBlock 三态渲染测试
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { levelOf } from '../src/store'
import StateBlock from '../src/components/StateBlock.vue'

describe('levelOf 按词数分档', () => {
  it('边界值与各档位', () => {
    expect(levelOf(0)).toBe('A1')        // 无词数信息
    expect(levelOf(7999)).toBe('A1')
    expect(levelOf(8000)).toBe('A2')
    expect(levelOf(19999)).toBe('A2')
    expect(levelOf(20000)).toBe('B1')
    expect(levelOf(44999)).toBe('B1')
    expect(levelOf(45000)).toBe('B2')
    expect(levelOf(79999)).toBe('B2')
    expect(levelOf(80000)).toBe('C1')
  })
})

describe('StateBlock 三态渲染', () => {
  it('loading 态展示加载文案', () => {
    const w = mount(StateBlock, { props: { status: 'loading', message: '书库加载中...' } })
    expect(w.text()).toContain('书库加载中...')
    expect(w.find('.fa-spin').exists()).toBe(true)
  })

  it('error 态展示失败信息与重试按钮，点击触发 retry', async () => {
    const w = mount(StateBlock, { props: { status: 'error', message: '网络异常' } })
    expect(w.text()).toContain('网络异常')
    await w.find('button').trigger('click')
    expect(w.emitted('retry')).toHaveLength(1)
  })

  it('empty 态展示图标 / 文案 / 提示，不渲染重试按钮', () => {
    const w = mount(StateBlock, {
      props: { status: 'empty', icon: 'fa-language', message: '暂无内容', hint: '去阅读页看看' },
    })
    expect(w.text()).toContain('暂无内容')
    expect(w.text()).toContain('去阅读页看看')
    expect(w.find('button').exists()).toBe(false)
  })
})
