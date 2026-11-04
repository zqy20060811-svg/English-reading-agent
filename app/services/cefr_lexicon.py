"""CEFR 词汇等级词典：加载本地 CSV，把英文单词映射到 A1~C2 等级。

词典来源与许可（合规记录）：
- CEFR-J Vocabulary Profile 1.5（约 7,000 词条，A1~B2）：
  东京外国语大学 Tono Laboratory 编制（Yukio Tono, CEFR-J Wordlist ver 1.5），
  允许研究与商业用途免费使用，但必须引用数据集（见下方 CITATION）。
- Octanove Vocabulary Profile C1/C2 1.0（约 1,700 词条，C1/C2）：
  Octanove Labs 编制，CC BY-SA 4.0 许可。
- 下载脚本：scripts/fetch_cefr_wordlist.py（文件保存在 data/cefr/，该目录已在 .gitignore，
  不会随仓库再分发；缺失时本模块优雅降级为全部 unknown）。

设计约束：
- 不使用 LLM 生成词汇等级（防止编造 CEFR 等级）
- 词典中查不到的词一律标记 unknown（低频词不等于难词，不做频率推断）
- 同一 headword 多个词性/条目时取最低等级（读者按最容易的释义理解）
"""

import csv
import re
from functools import lru_cache
from pathlib import Path

CITATION = (
    "Tono, Yukio. The CEFR-J Wordlist Version 1.5. Tokyo University of Foreign Studies. "
    "http://www.cefr-j.org/ ; Octanove Vocabulary Profile C1/C2 ver 1.0 (CC BY-SA 4.0)."
)

# 等级由低到高（用于「同词多级取最低」比较）
LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
_LEVEL_RANK = {lv: i for i, lv in enumerate(LEVELS)}

DATA_DIR = Path("data/cefr")
SOURCE_FILES = {
    "cefrj-vocabulary-profile-1.5.csv": "CEFR-J Vocabulary Profile 1.5",
    "octanove-vocabulary-profile-c1c2-1.0.csv": "Octanove Vocabulary Profile C1/C2 1.0",
}

# 单词 token 规则（与 personal_parser.word_count 一致，另允许纯词形）
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")


def normalize_token(token: str) -> str:
    """词条归一化：小写；去掉所有格与词尾撇号（fox' / fox's 不该变成不同词）"""
    token = token.strip().lower()
    while token and token[-1] in "'’":
        token = token[:-1]
    return token


def _clean_headword(headword: str) -> list[str]:
    """headword 可能含变体（a.m./A.M./am/AM）或多词短语：
    - 按 / 拆分变体，全部收录
    - 含空格的多词短语跳过（分析按单词 token 匹配，不匹配短语）
    """
    out = []
    for variant in headword.split("/"):
        norm = normalize_token(variant)
        if norm and " " not in norm:
            out.append(norm)
    return out


@lru_cache(maxsize=1)
def load_lexicon() -> dict[str, str]:
    """加载词典 {小写词: CEFR 等级}；文件缺失或损坏时返回空 dict（全部 unknown）。

    同一 headword 出现多个等级时取最低（最容易）等级。
    """
    lex: dict[str, str] = {}
    for filename, _desc in SOURCE_FILES.items():
        path = DATA_DIR / filename
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    word_list = _clean_headword(row.get("headword") or "")
                    level = (row.get("CEFR") or "").strip().upper()
                    if level not in _LEVEL_RANK or not word_list:
                        continue
                    for word in word_list:
                        old = lex.get(word)
                        if old is None or _LEVEL_RANK[level] < _LEVEL_RANK[old]:
                            lex[word] = level
        except (OSError, csv.Error):
            continue  # 单个文件损坏不影响另一个
    return lex


def classify_tokens(tokens: list[str]) -> dict[str, int]:
    """把 token 列表按 CEFR 等级分桶计数；词典查不到的记 unknown。"""
    lex = load_lexicon()
    counts = {lv: 0 for lv in LEVELS}
    counts["unknown"] = 0
    for token in tokens:
        word = normalize_token(token)
        counts[lex.get(word, "unknown")] += 1
    return counts


def level_of(token: str) -> str:
    """单个词的 CEFR 等级（查不到返回 unknown）"""
    return load_lexicon().get(normalize_token(token), "unknown")
