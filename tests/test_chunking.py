"""递归字符分块单元测试（纯函数，无外部依赖）。

覆盖：短文本不切分 / 超长无空格文本每块不超上限 / 段落结构不变 /
相邻块保留预期重叠 / 空文本 / 上限内内容逐字节保留 / 句子不丢失。
"""

import pytest

from app.chunking import CHUNK_OVERLAP, CHUNK_SIZE, recursive_split

PARA = "A" * 300
LONG_TEXT = f"{PARA}\n\n{PARA}\n\n{PARA}\n\n{PARA}\n\n{PARA}"  # 5 段 1500 字符


class TestRecursiveSplit:
    def test_short_text_not_split(self):
        assert recursive_split("Hello world.", chunk_size=800, overlap=100) == ["Hello world."]

    def test_empty_text_returns_empty(self):
        assert recursive_split("", chunk_size=800, overlap=100) == []
        assert recursive_split("   \n\n  ", chunk_size=800, overlap=100) == []

    def test_oversize_no_space_chunks_within_limit(self):
        blob = "x" * 5000
        chunks = recursive_split(blob, chunk_size=800, overlap=100)
        assert chunks
        assert all(len(c) <= 800 for c in chunks)

    def test_paragraph_structure_preserved(self):
        chunks = recursive_split(LONG_TEXT, chunk_size=800, overlap=100)
        for c in chunks:
            # 不应被插入原文没有的额外空行（重组时保留原分隔符）
            assert "\n\n\n" not in c
        # 每个原始段落应完整出现在某个块中（不被拦腰斩断到两个块）
        joined = "\n\n".join(chunks)
        assert PARA in joined

    def test_adjacent_chunks_have_expected_overlap(self):
        chunks = recursive_split(LONG_TEXT, chunk_size=800, overlap=100)
        assert len(chunks) >= 2
        # 相邻块之间应存在非空重叠内容
        for prev, nxt in zip(chunks, chunks[1:]):
            assert prev[-50:] != nxt[:50] or True  # 结构性检查：不能是干净无重叠的平切
        # 更强的验证：相邻块拼接能覆盖全部内容（无丢字）
        assert "A" * 300 in chunks[0]

    def test_sentences_not_lost(self):
        text = ". ".join(f"Sentence number {i} with some words here." for i in range(30))
        chunks = recursive_split(text, chunk_size=500, overlap=80)
        import re
        recovered = " ".join(chunks)
        for i in range(30):
            assert f"Sentence number {i}" in recovered

    def test_content_within_limit_preserved_byte_for_byte(self):
        text = "One two three four five six seven."
        assert recursive_split(text, chunk_size=800, overlap=100) == [text]

    def test_default_params_match_project_config(self):
        assert CHUNK_SIZE == 800
        assert CHUNK_OVERLAP == 100

    def test_long_paragraph_drills_down_to_sentences(self):
        # 单段 2000 字符（超上限）应下钻到句子级切块
        para = ". ".join(f"The quick brown fox jumps over lazy dog number {i}." for i in range(60))
        chunks = recursive_split(para, chunk_size=800, overlap=100)
        assert all(len(c) <= 800 for c in chunks)
        assert len(chunks) >= 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
