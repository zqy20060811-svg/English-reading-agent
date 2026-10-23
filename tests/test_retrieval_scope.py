"""两阶段范围检索（章节优先、不足扩全书、零命中拒答）单元测试。

用假 ChunkRepository 与假改写器隔离数据库与 LLM，不加载 BGE-M3。
"""

import pytest

from app.repositories.chunk_repository import ChunkHit
from app.services import retrieval_service as rs
from app.services.retrieval_service import (
    CHAPTER_CONFIDENT_DISTANCE,
    CHAPTER_MIN_HITS,
    RetrievalService,
)


def hit(chunk_id: int, chapter_id: int | None, distance: float | None = None) -> ChunkHit:
    return ChunkHit(
        chunk_id=chunk_id,
        book_id=1,
        chapter_id=chapter_id,
        chunk_index=0,
        chunk_text=f"chunk-{chunk_id}",
        distance=distance,
        bm25_rank=None,
    )


class FakeRepo:
    """按 chapter_id 是否为 None 区分章内/全书召回，并记录调用轨迹"""

    def __init__(self, chapter_vec=(), chapter_ft=(), book_vec=(), book_ft=()):
        self.chapter_vec = list(chapter_vec)
        self.chapter_ft = list(chapter_ft)
        self.book_vec = list(book_vec)
        self.book_ft = list(book_ft)
        self.calls: list[tuple[str, int | None]] = []

    async def search(self, vector, book_id=None, chapter_id=None, top_k=10):
        self.calls.append(("vec", chapter_id))
        source = self.chapter_vec if chapter_id is not None else self.book_vec
        return source[:top_k]

    async def search_fulltext(self, question, book_id=None, chapter_id=None, top_k=10):
        self.calls.append(("ft", chapter_id))
        source = self.chapter_ft if chapter_id is not None else self.book_ft
        return source[:top_k]


class CountingRewriter:
    def __init__(self):
        self.calls = 0

    async def __call__(self, question: str) -> str:
        self.calls += 1
        return f"rewritten({question})"


@pytest.fixture()
def patch_encode(monkeypatch):
    """绕开真实 BGE-M3 编码（单元测试不加载模型）"""
    monkeypatch.setattr(rs, "encode_query", lambda q: [0.01] * 1024)


def make_service(repo: FakeRepo) -> RetrievalService:
    return RetrievalService(db=None, chunk_repo=repo)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_chapter_confident_uses_chapter_only(patch_encode):
    """章内命中充足且距离小 → 只用章内证据，不查全书"""
    repo = FakeRepo(
        chapter_vec=[hit(1, 10, 0.45), hit(2, 10, 0.55)],
        chapter_ft=[hit(1, 10)],
    )
    rewriter = CountingRewriter()
    result = await make_service(repo).retrieve_with_scope(
        "问题", book_id=1, chapter_id=10, rewriter=rewriter
    )
    assert result.scope == "chapter"
    assert [h.chunk_id for h in result.hits] == [1, 2]
    assert ("vec", None) not in repo.calls and ("ft", None) not in repo.calls
    assert rewriter.calls == 1  # 改写只做一次，两阶段复用


@pytest.mark.anyio
async def test_chapter_weak_expands_to_book(patch_encode):
    """章内距离过大 → 扩展全书，章内命中去重后排最前，条数不超 top_k"""
    repo = FakeRepo(
        chapter_vec=[hit(1, 10, CHAPTER_CONFIDENT_DISTANCE + 0.2)],
        book_vec=[hit(1, 10, 0.4), hit(5, 20, 0.4), hit(6, 30, 0.5), hit(7, 40, 0.6), hit(8, 50, 0.7), hit(9, 60, 0.8)],
    )
    result = await make_service(repo).retrieve_with_scope(
        "问题", book_id=1, chapter_id=10, top_k=5
    )
    assert result.scope == "book"
    ids = [h.chunk_id for h in result.hits]
    assert ids[0] == 1  # 章内命中排最前
    assert len(ids) == 5
    assert len(ids) == len(set(ids))  # 去重


@pytest.mark.anyio
async def test_zero_hits_refuses(patch_encode):
    """全程零命中 → scope=none，供路由层直接拒答"""
    repo = FakeRepo()
    result = await make_service(repo).retrieve_with_scope(
        "问题", book_id=1, chapter_id=10
    )
    assert result.scope == "none"
    assert result.hits == [] and result.context == ""


@pytest.mark.anyio
async def test_chapter_hits_without_distance_expand(patch_encode):
    """章内命中但缺向量距离 → 不判定充分，扩展全书"""
    repo = FakeRepo(
        chapter_vec=[hit(1, 10, None), hit(2, 10, None)],
        book_vec=[hit(5, 20, 0.5)],
    )
    result = await make_service(repo).retrieve_with_scope(
        "问题", book_id=1, chapter_id=10
    )
    assert result.scope == "book"
    assert {h.chunk_id for h in result.hits} >= {1, 2, 5}


@pytest.mark.anyio
async def test_chapter_hits_below_min_expand(patch_encode):
    """章内命中数不足 CHAPTER_MIN_HITS → 扩展全书"""
    repo = FakeRepo(
        chapter_vec=[hit(1, 10, 0.30)],  # 距离很小但只有 1 条
        book_vec=[hit(5, 20, 0.5), hit(6, 30, 0.6)],
    )
    result = await make_service(repo).retrieve_with_scope(
        "问题", book_id=1, chapter_id=10
    )
    assert result.scope == "book"
    assert result.hits[0].chunk_id == 1
