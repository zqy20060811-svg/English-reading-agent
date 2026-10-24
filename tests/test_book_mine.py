"""阅读页「我的书单」并集逻辑单元测试（不依赖数据库，用假 Repository 隔离）。"""

import asyncio

from app.services.book_service import BookService


class FakeBook:
    def __init__(self, id):
        self.id = id


class FakeBookRepo:
    def __init__(self, books):
        self.books = {b.id: b for b in books}

    async def list_by_ids(self, book_ids):
        return [self.books[i] for i in book_ids if i in self.books]


class FakeProgressRepo:
    def __init__(self, book_ids):
        self.book_ids = book_ids

    async def list_book_ids(self, user_id):
        return list(self.book_ids)


class FakeInteractionRepo:
    def __init__(self, book_ids):
        self.book_ids = book_ids

    async def list_active_book_ids(self, user_id):
        return list(self.book_ids)


def make_service(read_ids, active_ids):
    svc = BookService.__new__(BookService)  # 跳过 __init__，直接注入假依赖
    svc.repo = FakeBookRepo([FakeBook(1), FakeBook(2), FakeBook(3)])
    svc.progress_repo = FakeProgressRepo(read_ids)
    svc.interaction_repo = FakeInteractionRepo(active_ids)
    return svc


def test_my_books_union_dedup_keeps_order():
    # 读过 2、3；点赞/收藏过 3、1 -> 并集去重且保持"先读过、后互动"的顺序
    svc = make_service([2, 3], [3, 1])
    books = asyncio.run(svc.list_my_books(user_id=7))
    assert [b.id for b in books] == [2, 3, 1]


def test_my_books_empty_when_no_interaction():
    svc = make_service([], [])
    assert asyncio.run(svc.list_my_books(user_id=7)) == []
