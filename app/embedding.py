"""BGE-M3 向量化模块：模型加载与文本编码（脚本与 API 共用，单例缓存避免重复加载）。

模型：BAAI/bge-m3（1024 维，中英文），向量已归一化，可直接用于 pgvector 余弦距离。
"""

from functools import lru_cache

MODEL_NAME = "BAAI/bge-m3"


@lru_cache(maxsize=1)
def get_embedding_model():
    """加载并向量模型（进程内单例，首次调用时下载/加载，之后复用）。"""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def encode_texts(texts: list[str]) -> list[list[float]]:
    """批量编码文本为归一化向量（同步 CPU 推理，API 侧请放入线程池调用）。"""
    vectors = get_embedding_model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def encode_query(text: str) -> list[float]:
    """编码单条查询文本。"""
    return encode_texts([text])[0]
