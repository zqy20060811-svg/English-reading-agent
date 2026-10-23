"""扩充低难度书库：从 Project Gutenberg 官网搜索页收集公版简易读物并爬取。

选书策略（面向英语初学者 A1~A2）：
    分级读本(readers)/识字课本(primer)/童话(fairy tales)/寓言(fables)/
    民间故事(folklore)/童谣(nursery rhymes)/儿童文学(children)/短篇故事
    均为公版书，语言简单、篇幅短，适合英语水平较低的用户。

说明：The Little Prince、Nate the Great、阿加莎简写本等仍在版权期内，
Gutenberg 不收录，故使用同类公版读物替代。

流程：
    1. 按主题词抓取 Gutenberg 搜索结果页（按下载量排序），收集候选书 ID；
    2. 逐本抓取详情页，校验公版/英文/纯文本可用性，解析书名/作者/年份；
    3. 下载正文 → 复用 scraper 清洗 → 落盘 data/books/{slug}/（info.json + content.txt）；
    4. 入库由 python -m app.crawler 同步（POST /books/sync 或 load_books 流程）。

用法：
    python -m app.scripts.crawl_easy_books                # 爬取至累计 110 本成功（只同步书籍信息）
    python -m app.scripts.crawl_easy_books --target 30    # 自定义目标
    python -m app.scripts.crawl_easy_books --ingest       # 爬完直连入库：同步→切章→分块
    python -m app.scripts.crawl_easy_books --ingest --embed  # 再加向量化（耗时长）
    python -m app.scripts.crawl_easy_books --dry-run      # 仅收集候选与元数据，不下载
"""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

import requests

from app.crawler.books_catalog import TXT_URL_TEMPLATE
from app.crawler.scraper import (
    DEFAULT_OUTPUT_DIR,
    REQUEST_INTERVAL,
    build_session,
    clean_gutenberg_text,
    count_words,
    save_book,
)
from app.crawler.books_catalog import BookMeta

# Gutenberg 详情页/搜索页
SITE = "https://www.gutenberg.org"
SEARCH_URL = f"{SITE}/ebooks/search/"
BOOK_PAGE_URL = f"{SITE}/ebooks/{{book_id}}/"

# 主题词 → 题材分类（低难度读物优先，按下载量排序保证Popular且质量可靠）
SEARCH_TERMS: list[tuple[str, str]] = [
    ("readers", "Easy Reader"),
    ("primer", "Easy Reader"),
    ("fairy tales", "Fairy Tale"),
    ("fables", "Fable"),
    ("folklore", "Folklore"),
    ("nursery rhymes", "Nursery Rhyme"),
    ("children", "Children"),
    ("allegories", "Allegory"),
    ("myths", "Myth"),
    ("legends", "Legend"),
]

# 单本书词数上下限（太短无阅读价值，太长不适合初学者）
MIN_WORDS = 1500
MAX_WORDS = 250000


def collect_candidates(session: requests.Session, per_term: int = 40) -> list[tuple[int, str]]:
    """按主题词收集候选书 ID（去重保序），返回 [(gutenberg_id, genre), ...]。"""
    seen: dict[int, str] = {}
    for query, genre in SEARCH_TERMS:
        try:
            resp = session.get(
                SEARCH_URL,
                params={"query": query, "sort_order": "downloads"},
                timeout=60,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"搜索 '{query}' 失败：{exc}")
            continue
        ids = list(dict.fromkeys(re.findall(r"/ebooks/(\d+)", resp.text)))
        new_count = sum(1 for i in map(int, ids) if i not in seen)
        for gid in ids:
            seen.setdefault(int(gid), genre)
        print(f"搜索 '{query}'：新增候选 {new_count}，累计 {len(seen)}")
        time.sleep(REQUEST_INTERVAL)
    # 每个主题只保留前 per_term 个（按下载量排序，天然取热门）
    used: dict[int, str] = {}
    for query, genre in SEARCH_TERMS:
        count = 0
        for gid, g in seen.items():
            if g == genre:
                used.setdefault(gid, genre)
                count += 1
                if count >= per_term:
                    break
    return list(used.items())


def fetch_meta(session: requests.Session, gutenberg_id: int) -> dict | None:
    """抓取详情页元数据；非公版/非英文/无纯文本的返回 None。"""
    url = BOOK_PAGE_URL.format(book_id=gutenberg_id)
    try:
        resp = session.get(url, timeout=60)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    html = resp.text

    if "Public domain in the USA" not in html:
        return None
    if ">English<" not in html:
        return None

    m = re.search(r"<title>\s*(.+?)\s*\|\s*Project Gutenberg</title>", html, re.DOTALL)
    if not m:
        return None
    full = re.sub(r"\s+", " ", m.group(1)).strip()
    # "The Tale of Peter Rabbit by Beatrix Potter" → (书名, 作者)；书名中也可能含 by，取最后一个
    if " by " in full:
        title, author = (p.strip() for p in full.rsplit(" by ", 1))
    else:
        title, author = full, "Anonymous"

    ym = re.search(r"Release Date:[^(\[]{0,40}?(\d{4})", html)
    year = int(ym.group(1)) if ym else 1900

    return {"title": title, "author": author, "year": year}


# 质量过滤：语言教学类外文书（如 A First Spanish Reader）标题特征
_FOREIGN_TEACHING_RE = re.compile(
    r"\b(?:spanish|french|german|italian|latin)\b.{0,30}\b(?:reader|textbook|grammar|course|anthology|composition|conversation)\b",
    re.IGNORECASE,
)
# Easy Reader 白名单关键词（防止 'The Common Reader' 之类的论说文混入）
_EASY_TITLE_RE = re.compile(r"reader|primer|speller|first book|child", re.IGNORECASE)


def quality_ok(title: str, genre: str, words: int) -> bool:
    """候选书质量过滤：语言教学外文书与不相关的论说文剔除。"""
    if _FOREIGN_TEACHING_RE.search(title):
        return False
    if genre == "Easy Reader" and not _EASY_TITLE_RE.search(title):
        return False
    if genre == "Easy Reader" and words > 80000:
        return False
    return True


async def sync_books_to_db() -> None:
    """爬取完成后把 data/books 信息同步入库（复用 BookService.sync_from_crawler）。"""
    from app.db.database import AsyncSessionLocal
    from app.services.book_service import BookService

    async with AsyncSessionLocal() as s:
        result = await BookService(s).sync_from_crawler()
    print(f"入库完成：发现 {result.total_found} 本，新增 {result.created} 本，更新 {result.updated} 本")


def main(target: int, dry_run: bool, skip_sync: bool, ingest: bool = False, embed: bool = False) -> None:
    session = build_session()

    # 各环节耗时统计（秒）
    stage = {"候选收集": 0.0, "元数据": 0.0, "下载": 0.0, "清洗": 0.0, "落盘": 0.0, "间隔等待": 0.0}
    new_ids: list[int] = []  # 本次成功落盘的书（古登堡 ID），供直连入库流水线使用

    # 已有本地书目（跳过重复）
    existing_ids: set[int] = set()
    for info_path in DEFAULT_OUTPUT_DIR.glob("*/info.json"):
        info = json.loads(info_path.read_text(encoding="utf-8"))
        existing_ids.add(info["gutenberg_id"])
    print(f"本地已有 {len(existing_ids)} 本书，目标再爬 {target} 本")

    t0 = time.perf_counter()
    candidates = collect_candidates(session)
    stage["候选收集"] = time.perf_counter() - t0
    print(f"候选池：{len(candidates)} 本（耗时 {stage['候选收集']:.1f}s）")

    succeeded = 0
    for gutenberg_id, genre in candidates:
        if gutenberg_id in existing_ids:
            continue
        if succeeded >= target:
            break
        t0 = time.perf_counter()
        meta = fetch_meta(session, gutenberg_id)
        stage["元数据"] += time.perf_counter() - t0
        if meta is None:
            continue
        if dry_run:
            print(f"  [候选] #{gutenberg_id} {meta['title']} - {meta['author']} ({meta['year']}) [{genre}]")
            succeeded += 1
            continue
        url = TXT_URL_TEMPLATE.format(book_id=gutenberg_id)
        try:
            t0 = time.perf_counter()
            raw = session.get(url, timeout=120)
            if raw.status_code == 404:
                # 部分书没有 pg{N}.txt，回退到 utf-8 版本
                url = url[:-4] + ".txt.utf-8"
                raw = session.get(url, timeout=120)
            raw.raise_for_status()
            raw.encoding = "utf-8"
            stage["下载"] += time.perf_counter() - t0

            t0 = time.perf_counter()
            content = clean_gutenberg_text(raw.text)
            words = count_words(content)
            stage["清洗"] += time.perf_counter() - t0
            if not (MIN_WORDS <= words <= MAX_WORDS) or not quality_ok(meta["title"], genre, words):
                print(f"  [跳过] {meta['title']}：{words} 词或质量过滤未通过")
                continue

            t0 = time.perf_counter()
            book = BookMeta(
                gutenberg_id=gutenberg_id,
                title=meta["title"],
                author=meta["author"],
                year=meta["year"],
                genre=genre,
                synopsis=(
                    f"A public domain {genre.lower()} from Project Gutenberg with simple, "
                    f"classic English — well suited for beginner-level English readers."
                ),
            )
            info = save_book(book, content, DEFAULT_OUTPUT_DIR)
            stage["落盘"] += time.perf_counter() - t0

            existing_ids.add(gutenberg_id)
            new_ids.append(gutenberg_id)
            succeeded += 1
            print(
                f"  [✓ {succeeded}/{target}] {info['title']}（{genre}，{words} 词）"
                f" [下载 {stage['下载']:.1f}s 累计]"
            )
        except Exception as exc:
            print(f"  [失败] #{gutenberg_id} {meta.get('title', '')}: {exc}")
        t0 = time.perf_counter()
        time.sleep(REQUEST_INTERVAL)
        stage["间隔等待"] += time.perf_counter() - t0

    print(f"爬取完成：本次成功 {succeeded} 本")
    if succeeded:
        print("各环节累计耗时：")
        for name, sec in stage.items():
            if sec:
                print(f"  {name}: {sec:.1f}s")
    if dry_run:
        return

    if ingest or embed:
        # 直连入库流水线：书籍同步 → 章节切分 → 分块（→ 可选向量化）
        from app.pipeline import run_ingest

        asyncio.run(run_ingest(new_ids, embed=embed))
    elif not skip_sync and succeeded > 0:
        # 旧行为：只同步书籍信息
        t0 = time.perf_counter()
        asyncio.run(sync_books_to_db())
        print(f"入库同步耗时：{time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="爬取公版低难度英语读物扩充书库")
    parser.add_argument("--target", type=int, default=110, help="本次目标爬取数量")
    parser.add_argument("--dry-run", action="store_true", help="仅收集候选与元数据，不下载")
    parser.add_argument("--skip-sync", action="store_true", help="爬完不入库（后续手动同步）")
    parser.add_argument(
        "--ingest", action="store_true",
        help="爬完直连入库流水线：书籍同步→章节切分→分块（含书籍同步，忽略 --skip-sync）",
    )
    parser.add_argument(
        "--embed", action="store_true",
        help="在 --ingest 基础上同时向量化（CPU 约 2.4 块/秒，千块约 8 分钟）",
    )
    args = parser.parse_args()
    main(args.target, args.dry_run, args.skip_sync, args.ingest, args.embed)
    sys.exit(0)
