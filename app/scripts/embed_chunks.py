"""命令行：为 book_chunks 中缺 embedding 的块生成向量（BAAI/bge-m3 本地推理，1024 维中英文）。

复用 app.pipeline.embed_missing_chunks 核心逻辑。

用法：python -m app.scripts.embed_chunks [--limit N]
"""
import argparse
import asyncio

from app.embedding import MODEL_NAME
from app.pipeline import embed_missing_chunks


async def main(limit: int | None = None) -> None:
    stats = await embed_missing_chunks(limit)
    n = stats["chunks"]
    if n == 0:
        print("没有缺 embedding 的块，无需处理")
        return
    print(
        f"embedding 生成完成：{n} 块（模型 {MODEL_NAME}，1024 维，已归一化）\n"
        f"耗时：模型加载 {stats['model_s']:.1f}s / 编码 {stats['encode_s']:.1f}s / 写库 {stats['db_s']:.1f}s"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="最多处理的块数")
    args = parser.parse_args()
    asyncio.run(main(args.limit))
