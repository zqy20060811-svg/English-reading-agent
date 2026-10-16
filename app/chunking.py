"""递归字符分块纯函数（离线管道用，不含数据库逻辑）。

分块参数：chunk_size=800 字符、overlap=100 字符，优先保留段落/句子等自然边界。
"""

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
    seps = separators if separators is not None else SEPARATORS
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    sep, rest = seps[0], seps[1:]

    if sep == "":  # 兜底：硬切并保留 overlap
        step = chunk_size - overlap
        return [text[i : i + chunk_size] for i in range(0, len(text), step)]

    # 按当前分隔符切分，重组时保留分隔符结构
    pieces = [p for p in text.split(sep) if p.strip()]
    # 递归下钻：仍超长的片段用下一级分隔符继续切
    flat: list[str] = []
    for p in pieces:
        if len(p) <= chunk_size:
            flat.append(p)
        elif rest:
            flat.extend(recursive_split(p, chunk_size, overlap, rest))
        else:  # 无更多分隔符，兜底硬切
            step = chunk_size - overlap
            flat.extend(p[i : i + chunk_size] for i in range(0, len(p), step))

    return _merge(flat, sep, chunk_size, overlap)


def _merge(pieces: list[str], sep: str, chunk_size: int, overlap: int) -> list[str]:
    """把达标片段按顺序聚合成接近 chunk_size 的块，块间保留 overlap。"""
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0

    for p in pieces:
        add_len = len(p) if not cur else cur_len + len(sep) + len(p)
        if add_len > chunk_size and cur:
            chunks.append(sep.join(cur))
            # 回收尾部整数个片段作为 overlap，保证重叠部分也是完整片段
            tail: list[str] = []
            tail_len = 0
            for q in reversed(cur):
                q_len = len(q) if not tail else tail_len + len(sep) + len(q)
                if tail_len + q_len > overlap:
                    break
                tail.insert(0, q)
                tail_len = q_len
            cur, cur_len = tail, tail_len
        cur.append(p)
        cur_len = len(p) if cur_len == 0 and len(cur) == 1 else cur_len + len(sep) + len(p)

    if cur:
        chunks.append(sep.join(cur))
    # 极小尾巴并入前一块，避免产生大量碎片块
    if len(chunks) >= 2 and len(chunks[-1]) < overlap:
        chunks[-2] = chunks[-2] + sep + chunks[-1]
        chunks.pop()
    return chunks
