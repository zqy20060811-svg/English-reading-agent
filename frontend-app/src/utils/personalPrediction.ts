// 个人书籍预测辅助（阶段D）：正文不做任何高亮，仅保留词条归一化，
// 用于"点击单词 → 命中预测生词表 → 弹层附加 CEFR/次数/收藏信息"的匹配。
// 归一化口径与后端 cefr_lexicon.normalize_token 一致（小写 + 去尾部撇号）。

export function normalizeWord(token: string): string {
  let w = token.trim().toLowerCase()
  while (w && (w.endsWith("'") || w.endsWith('’'))) w = w.slice(0, -1)
  return w
}
