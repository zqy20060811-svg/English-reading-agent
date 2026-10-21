"""章节切分与入库业务逻辑：解析 data/books 目录下的本地书源，切分章节存入 book_chapters 表。"""

import json
import re
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.models.book import Book
from app.models.book_chapter import BookChapter

# 本地书源根目录（相对于项目根目录）
DEFAULT_BOOKS_DIR = Path("data/books")

# 罗马数字 → 整数
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(s: str) -> int:
    total, prev = 0, 0
    for ch in reversed(s.upper()):
        val = _ROMAN[ch]
        total = total - val if val < prev else total + val
        prev = max(prev, val)
    return total


# 候选章节标题的匹配模式（按行匹配）
_HEADING_PATTERNS = [
    # Chapter I. / CHAPTER 1. Loomings. / Stave II: xxx / Letter 1
    re.compile(r"^\s*(CHAPTER|STAVE|LETTER)\s+([IVXLCDM]+|\d+)\b[.:\-\s]*(.*)$", re.IGNORECASE),
    # 罗马数字+点+全大写标题，如 "I. A SCANDAL IN BOHEMIA"
    re.compile(r"^\s*([IVXLCDM]{1,4})\.\s+([A-Z][A-Z\s'’\-—]{2,})\s*$"),
    # 罗马数字+点单独成行（标题在下一行），如 "I."
    re.compile(r"^\s*([IVXLCDM]{1,4})\.\s*$"),
]

# 干扰行过滤：目录中的方括号行、插图说明、页码引导点
_NOISE_RE = re.compile(r"\]\s*$|\.\s+\.\s+\.|Heading to|Tailpiece")

# 罗马数字单独成行（无点号，标题在下一行），如 Treasure Island 正文的 "I"
_BARE_ROMAN_RE = re.compile(r"^\s*([IVXLCDM]{1,8})\s*$")

# 目录区判定参数：连续 ≥ TOC_RUN_MIN 个候选、相邻间距 ≤ TOC_GAP 行 → 整区剔除。
# TOC_GAP 取 3：目录条目几乎逐行紧排（间距 1~2），而目录末条与正文第一章标题
# 之间一般隔 4 行以上，避免把正文第一章一起吞掉。
TOC_RUN_MIN = 4
TOC_GAP = 3
# 窗口去重：相邻 ≤ WIN_GAP 行的候选只保留最后一个（目录标题+正文标题连排场景）
WIN_GAP = 8
# 过小章节并入前章的词数阈值
MIN_WORDS = 150


def _line_heading(line: str) -> tuple[int, str] | None:
    """识别一行是否章节标题，返回 (序号, 标题) 或 None"""
    if _NOISE_RE.search(line):
        return None
    m = _HEADING_PATTERNS[0].match(line)
    if m:
        label = m.group(2)
        idx = int(label) if label.isdigit() else roman_to_int(label)
        title = m.group(3).strip()
        return idx, title
    m = _HEADING_PATTERNS[1].match(line)
    if m:
        return roman_to_int(m.group(1)), m.group(2).strip()
    m = _HEADING_PATTERNS[2].match(line)
    if m:
        return roman_to_int(m.group(1)), ""
    return None


def split_chapters(content: str) -> list[tuple[str, str]]:
    """把整书文本切分为 [(标题, 正文), ...]。

    流程：
    1. 逐行收集候选标题（过滤目录方括号行/插图说明等噪声）；
    2. 剔除目录区：连续 ≥ TOC_RUN_MIN 个候选且相邻间距 ≤ TOC_GAP 行的整段；
    3. 窗口去重：相邻 ≤ WIN_GAP 行的候选只留最后一个（如目录标题与正文标题连排）；
    4. 按保留的标题行切分，正文过小（< MIN_WORDS 词且非末章）的章节并入前一章。
    """
    lines = content.splitlines()
    candidates: list[tuple[int, int, str]] = []  # (行号, 章节逻辑序号, 标题或空)
    for i, line in enumerate(lines):
        head = _line_heading(line)
        if not head:
            m = _BARE_ROMAN_RE.match(line)
            # 罗马数字单独成行：仅当其后 3 行内出现"像标题"的行（≥3 个字母）
            # 才认定为章节号，避免把行文中的孤立代词 "I" 误判为章节标题
            if m:
                for k in range(i + 1, min(i + 4, len(lines))):
                    nxt = lines[k].strip()
                    if not nxt:
                        continue
                    if len(re.findall(r"[A-Za-z]", nxt)) >= 3:
                        head = (roman_to_int(m.group(1)), "")
                    break
        if head:
            candidates.append((i, head[0], head[1]))

    if not candidates:
        return [("Full Text", content.strip())]

    # 2) 密集区分析：间距 ≤ TOC_GAP 的候选构成"密集区"；区内序号从 N 跳回 1 处
    #    为目录→正文的分界（正文第一章重新从 1 编号）。长度 ≥ TOC_RUN_MIN 的
    #    子区判定为目录区，整段剔除。
    runs: list[list[tuple[int, int, str]]] = []
    for cand in candidates:
        if runs and cand[0] - runs[-1][-1][0] <= TOC_GAP:
            runs[-1].append(cand)
        else:
            runs.append([cand])
    survivors: list[tuple[int, int, str]] = []
    for run in runs:
        # 区内按序号回退位置切成子区
        sub_runs: list[list[tuple[int, int, str]]] = [[run[0]]]
        for prev, cand in zip(run, run[1:]):
            if cand[1] < prev[1]:
                sub_runs.append([cand])
            else:
                sub_runs[-1].append(cand)
        for sub in sub_runs:
            if len(sub) < TOC_RUN_MIN:
                survivors.extend(sub)
    if not survivors:
        return [("Full Text", content.strip())]

    # 3) 窗口去重
    kept: list[tuple[int, int, str]] = []
    for i, cand in enumerate(survivors):
        next_ln = survivors[i + 1][0] if i + 1 < len(survivors) else 10**9
        if next_ln - cand[0] <= WIN_GAP:
            continue
        kept.append(cand)
    if not kept:
        return [("Full Text", content.strip())]

    # 4) 按标题行切分（首章把标题之前的扉页/版权页内容一并保留，避免丢内容）
    chapters: list[tuple[str, str]] = []
    for j, (ln, _idx, title) in enumerate(kept):
        end = kept[j + 1][0] if j + 1 < len(kept) else len(lines)
        start = ln + 1
        if not title:
            # 标题在下一行（如 Time Machine / Alice / Moby 格式），
            # 跳过 [Illustration 等噪声行
            for k in range(start, min(start + 6, end)):
                s = lines[k].strip()
                if s and not s.startswith("["):
                    title = s
                    start = k + 1
                    break
        first_ln = 0 if j == 0 else start
        chapters.append((title or "", "\n".join(lines[first_ln:end]).strip()))

    # 过小章节并入前一章（末章除外），重新编号
    merged: list[tuple[str, str]] = []
    for j, (title, body) in enumerate(chapters):
        if merged and j < len(chapters) - 1 and len(body.split()) < MIN_WORDS:
            prev_title, prev_body = merged[-1]
            merged[-1] = (prev_title, f"{prev_body}\n\n{title}\n\n{body}".strip())
        else:
            merged.append((title, body))

    return [
        (title or f"Chapter {i}", body)
        for i, (title, body) in enumerate(merged, start=1)
    ]


def _word_count(text: str) -> int:
    return len(text.split())


async def sync_chapters_from_local(
    books_dir: Path = DEFAULT_BOOKS_DIR, session: AsyncSession | None = None
) -> dict:
    """解析本地书源目录，切分章节并全量替换入库（幂等）。"""
    own_session = session is None
    if own_session:
        session = AsyncSessionLocal()
    stats = {"books": 0, "chapters": 0, "skipped": 0}
    try:
        for book_dir in sorted(books_dir.iterdir()):
            info_path = book_dir / "info.json"
            content_path = book_dir / "content.txt"
            if not info_path.exists() or not content_path.exists():
                continue
            info = json.loads(info_path.read_text(encoding="utf-8"))
            book = (
                await session.execute(
                    select(Book).where(Book.gutenberg_id == info["gutenberg_id"])
                )
            ).scalar_one_or_none()
            if book is None:
                stats["skipped"] += 1
                continue

            content = content_path.read_text(encoding="utf-8")
            parts = split_chapters(content)

            # 幂等 upsert：按 (book_id, chapter_index) 更新已存在的章节（保持主键不变，
            # 避免下游 book_chunks.chapter_id 全部失联），多退少补
            existing = (
                await session.execute(select(BookChapter).where(BookChapter.book_id == book.id))
            ).scalars().all()
            by_index = {c.chapter_index: c for c in existing}
            for i, (title, body) in enumerate(parts, start=1):
                row = by_index.get(i)
                if row is None:
                    session.add(
                        BookChapter(
                            book_id=book.id,
                            chapter_index=i,
                            title=title[:255],
                            content=body,
                            word_count=_word_count(body),
                        )
                    )
                else:
                    row.title = title[:255]
                    row.content = body
                    row.word_count = _word_count(body)
            stale_ids = [c.id for idx, c in by_index.items() if idx > len(parts)]
            if stale_ids:
                await session.execute(delete(BookChapter).where(BookChapter.id.in_(stale_ids)))
            stats["books"] += 1
            stats["chapters"] += len(parts)
        await session.commit()
        return stats
    finally:
        if own_session:
            await session.close()
