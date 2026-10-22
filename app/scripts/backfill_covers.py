"""命令行：从 Open Library 为书目匹配封面图，回填 books.cover_url 并写入 info.json。

封面来源：https://openlibrary.org/search.json?title=...&author=...（免费、无需 Key）
取首个带 cover_i 的结果，生成 covers.openlibrary.org 的 L 尺寸图片 URL。
未匹配到的书保持 NULL，前端用渐变色占位兜底。

用法：python -m app.scripts.backfill_covers
"""
import asyncio
import html
import json
import time
from pathlib import Path

import requests
from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.models.book import Book

BOOKS_DIR = Path("data/books")
SEARCH_URL = "https://openlibrary.org/search.json"
COVER_URL_TEMPLATE = "https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
REQUEST_INTERVAL = 1.0  # 对 Open Library 保持礼貌


def search_cover(title: str, author: str) -> str | None:
    """按书名+作者搜索 Open Library，返回封面 URL 或 None。"""
    params = {"title": title, "fields": "cover_i", "limit": 3}
    # 空作者必须省略参数（传 author= 空值会触发 Open Library 500）
    if author:
        params["author"] = author
    try:
        resp = requests.get(SEARCH_URL, params=params, timeout=30)
        resp.raise_for_status()
        for doc in resp.json().get("docs", []):
            if doc.get("cover_i"):
                return COVER_URL_TEMPLATE.format(cover_id=doc["cover_i"])
    except requests.RequestException as exc:
        print(f"    请求失败：{exc}")
    return None


def clean_title(title: str) -> str:
    """去掉副标题与括号注释，提高搜索命中率（如 'X; Or, Y (from Z)' -> 'X'）。"""
    title = html.unescape(title)  # 爬取标题可能残留 HTML 转义符（如 &amp;）
    for sep in (";", ":", "(", "[", "—", " -- "):
        title = title.split(sep, 1)[0]
    return title.strip().rstrip(".")


def search_cover_with_retry(title: str, author: str) -> tuple[str | None, str]:
    """三轮降级搜索：原名+作者 -> 清理书名+作者姓氏 -> 清理书名。返回 (URL, 命中方式)。"""
    url = search_cover(title, author)
    if url:
        return url, "原名+作者"
    short_title = clean_title(title)
    last_name = author.split()[-1] if author else ""
    if last_name:
        url = search_cover(short_title, last_name)
        if url:
            return url, "清理书名+作者姓氏"
    url = search_cover(short_title, "")
    if url:
        return url, "仅清理书名"
    return None, ""


async def main() -> None:
    async with AsyncSessionLocal() as s:
        books = (
            (await s.execute(select(Book).where(Book.cover_url.is_(None)).order_by(Book.id)))
            .scalars()
            .all()
        )
        print(f"共 {len(books)} 本书待匹配封面（已有封面的自动跳过）")
        matched = 0
        for book in books:
            cover_url, how = search_cover_with_retry(book.title, book.author)
            if cover_url:
                book.cover_url = cover_url
                matched += 1
                print(f"  [✓] {book.title}: {cover_url}（{how}）")
            else:
                print(f"  [×] {book.title}: 未匹配到封面")
            # 同步写回本地 info.json（按 gutenberg_id 定位目录），便于追溯
            info_path = None
            for p in BOOKS_DIR.glob("*/info.json"):
                if json.loads(p.read_text(encoding="utf-8")).get("gutenberg_id") == book.gutenberg_id:
                    info_path = p
                    break
            if info_path:
                info = json.loads(info_path.read_text(encoding="utf-8"))
                info["cover_url"] = cover_url
                info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
            time.sleep(REQUEST_INTERVAL)
        await s.commit()
    print(f"完成：{matched}/{len(books)} 本匹配到封面")


if __name__ == "__main__":
    asyncio.run(main())
