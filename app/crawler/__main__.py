"""命令行入口：python -m app.crawler [--limit 15] [--output-dir data/books]"""

import argparse
from pathlib import Path

from app.crawler.scraper import DEFAULT_OUTPUT_DIR, crawl_books


def main() -> None:
    parser = argparse.ArgumentParser(description="爬取 Project Gutenberg 公有领域英文书")
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="最多抓取的书本数量（书单共 20 本，默认 15）",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="输出目录，默认为项目根目录下的 data/books",
    )
    args = parser.parse_args()

    crawl_books(limit=args.limit, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
