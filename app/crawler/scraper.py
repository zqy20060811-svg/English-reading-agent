"""爬虫核心逻辑：下载 Gutenberg 纯文本，清洗页眉页脚，落盘保存书籍信息与正文。

输出目录结构：
    data/books/
        index.json                    # 所有成功抓取书籍的汇总信息
        pride_and_prejudice/
            info.json                 # 单本书籍信息（书名/作者/年份/来源/字数等）
            content.txt               # 清洗后的书籍正文
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from app.crawler.books_catalog import (
    BOOK_CATALOG,
    TXT_URL_TEMPLATE,
    BookMeta,
    book_to_dict,
)

# 默认输出目录：项目根目录下 data/books
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "books"

# 请求头：Gutenberg 要求声明 User-Agent
HEADERS = {
    "User-Agent": "EnglishReadingAgent/1.0 (educational reading project; contact: local-dev)"
}

# Gutenberg 文本的开始/结束标记，用于去掉许可声明页眉页脚
START_MARKER = re.compile(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.IGNORECASE)
END_MARKER = re.compile(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.IGNORECASE)

# 单次请求超时（秒）
REQUEST_TIMEOUT = 60
# 失败重试次数
MAX_RETRIES = 3
# 每本书之间的间隔（秒），对目标站点保持礼貌
REQUEST_INTERVAL = 2.0


def slugify(title: str) -> str:
    """书名转目录名：小写、空格换连字符，仅保留字母数字和连字符。"""
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug.strip("-")


def build_session() -> requests.Session:
    """创建带请求头的会话。"""
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def download_text(session: requests.Session, url: str) -> str:
    """下载文本内容，失败自动重试。"""
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        except requests.RequestException as exc:
            last_error = exc
            wait = attempt * 3  # 逐次加长等待：3s、6s、9s
            print(f"    [重试 {attempt}/{MAX_RETRIES}] 下载失败：{exc}，{wait}s 后重试")
            time.sleep(wait)
    raise RuntimeError(f"下载失败（已重试 {MAX_RETRIES} 次）：{url}") from last_error


def clean_gutenberg_text(raw: str) -> str:
    """去掉 Gutenberg 页眉/页脚许可声明，保留正文。"""
    start_match = START_MARKER.search(raw)
    end_match = END_MARKER.search(raw)

    start = start_match.end() if start_match else 0
    end = end_match.start() if end_match else len(raw)
    text = raw[start:end].strip()

    # 规范换行符，去掉行尾空白
    text = text.replace("\r\n", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    # 压缩 3 个以上连续空行为 2 个
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def count_words(text: str) -> int:
    """统计英文单词数。"""
    return len(re.findall(r"[A-Za-z']+", text))


def save_book(book: BookMeta, content: str, output_dir: Path) -> dict:
    """将单本书的信息与正文写入磁盘，返回书籍信息字典。"""
    book_dir = output_dir / slugify(book.title)
    book_dir.mkdir(parents=True, exist_ok=True)

    info = {
        **book_to_dict(book),
        "source": "Project Gutenberg (public domain)",
        "source_url": TXT_URL_TEMPLATE.format(book_id=book.gutenberg_id),
        "language": "en",
        "word_count": count_words(content),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }

    (book_dir / "info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (book_dir / "content.txt").write_text(content, encoding="utf-8")
    return info


def crawl_books(
    limit: int | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> list[dict]:
    """爬取书单中的书籍，返回成功抓取的书籍信息列表。

    Args:
        limit: 最多抓取数量，None 表示抓取全部书单。
        output_dir: 输出目录。
    """
    books = BOOK_CATALOG if limit is None else BOOK_CATALOG[:limit]
    output_dir.mkdir(parents=True, exist_ok=True)

    session = build_session()
    results: list[dict] = []
    failed: list[str] = []

    print(f"开始爬取：计划 {len(books)} 本，输出目录 {output_dir}")
    for idx, book in enumerate(books, start=1):
        print(f"[{idx}/{len(books)}] {book.title} - {book.author}")
        url = TXT_URL_TEMPLATE.format(book_id=book.gutenberg_id)
        try:
            raw = download_text(session, url)
            content = clean_gutenberg_text(raw)
            if len(content) < 1000:
                raise RuntimeError("清洗后正文过短，疑似抓取异常")
            info = save_book(book, content, output_dir)
            results.append(info)
            print(f"    成功：{info['word_count']} 词")
        except Exception as exc:
            failed.append(book.title)
            print(f"    失败：{exc}")
        if idx < len(books):
            time.sleep(REQUEST_INTERVAL)

    # 写入汇总索引
    index_path = output_dir / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_success": len(results),
                "total_failed": len(failed),
                "failed_titles": failed,
                "books": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"完成：成功 {len(results)} 本，失败 {len(failed)} 本，索引已写入 {index_path}")
    return results
