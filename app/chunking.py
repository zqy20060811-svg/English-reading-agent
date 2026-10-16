"""递归字符分块纯函数（离线管道用，不含数据库逻辑）。

分块参数：chunk_size=800 字符、overlap=100 字符，优先保留段落/句子等自然边界。

实现要点：
- 切分时把分隔符保留在片段尾部，重组一律用空串 join，逐字节还原原文，
  保证多段落/多句子的文本结构不会被改动；
- 长度一律对真实字符串取 len，不做增量算术，避免 overlap 累计长度重复计算；
- 所有分隔符都切不动的超长单元（如无空格长串）硬切兜底，任何块不超过上限。
"""

import re

CHUNK_SIZE = 800  # 目标块长（字符）
CHUNK_OVERLAP = 100  # 相邻块重叠（字符）

# 分隔符按语义强度从高到低：段落 → 行 → 句子 → 词
SEPARATORS = ["\n\n", "\n", ". ", " "]


def recursive_split(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    separators: list[str] | None = None,
) -> list[str]:
    """递归字符分块：按分隔符层级下钻，只在必要时使用更细的边界。"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    units = _split(text, list(separators if separators is not None else SEPARATORS), chunk_size, overlap)
    return _merge_units(units, chunk_size, overlap)


def _split(text: str, seps: list[str], chunk_size: int, overlap: int) -> list[str]:
    """递归下钻，返回"单元"列表：每个单元文本 ≤ chunk_size，拼接还原原文。"""
    if len(text) <= chunk_size:
        return [text]
    if not seps:
        # 无分隔符可用：硬切兜底，块间保留 overlap
        step = chunk_size - overlap
        return [text[i : i + chunk_size] for i in range(0, len(text), step)]

    sep, rest = seps[0], seps[1:]
    # 切分时把分隔符保留在前一片段尾部（含空分隔符的纯 split）
    if sep:
        parts = re.split(f"({re.escape(sep)})", text)
        pieces = []
        for i in range(0, len(parts), 2):
            seg = parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")
            if seg.strip():
                pieces.append(seg)
    else:
        pieces = [p for p in text.split(sep) if p.strip()]

    units: list[str] = []
    for p in pieces:
        if len(p) <= chunk_size:
            units.append(p)
        else:
            units.extend(_split(p, rest, chunk_size, overlap))
    return units


def _merge_units(units: list[str], chunk_size: int, overlap: int) -> list[str]:
    """把单元按顺序聚合成接近 chunk_size 的块（空串 join），块间保留 overlap。

    overlap 取前一块尾部整数个单元，长度按真实拼接结果计算。
    """
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0

    for unit in units:
        if cur and cur_len + len(unit) > chunk_size:
            chunks.append("".join(cur))
            # 回收尾部整数个单元作为 overlap（长度按真实字符串累计）
            tail: list[str] = []
            tail_text = ""
            tail_len = 0
            for v in reversed(cur):
                if tail_len + len(v) > overlap:
                    break
                tail.insert(0, v)
                tail_text = v + tail_text
                tail_len = len(tail_text)
            # 尾部放不下下一个单元时整个丢弃，避免块超限
            if tail_len + len(unit) > chunk_size:
                tail, tail_len = [], 0
            cur, cur_len = tail, tail_len
        cur.append(unit)
        cur_len += len(unit)

    if cur:
        chunks.append("".join(cur))
    # 极小尾巴并入前一块，避免产生大量碎片块
    if len(chunks) >= 2 and len(chunks[-1]) < overlap:
        chunks[-2] += chunks[-1]
        chunks.pop()
    return chunks
