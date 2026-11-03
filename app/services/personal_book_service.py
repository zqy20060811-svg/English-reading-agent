"""个人书籍业务逻辑：上传解析、隔离查询、删除清理、阅读进度。

隔离原则：
- 所有按 id 的读取/删除都必须先经 `_get_owned`（user_id 条件在仓储层强制）
- 不做「他人的书」与「不存在」的区分，统一 404，避免探测
"""

import asyncio
import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.database import get_db
from app.models.personal_book import PersonalBook
from app.models.user import User
from app.repositories.personal_book_repository import PersonalBookRepository
from app.repositories.personal_progress_repository import PersonalProgressRepository
from app.schemas.personal_book import (
    PersonalBookOut,
    PersonalBookUploadOut,
    PersonalChapterDetailOut,
    PersonalChapterOut,
    PersonalProgressOut,
    PersonalProgressUpdate,
)
from app.services.personal_parser import ParseError, parse_upload, word_count


class PersonalBookService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = PersonalBookRepository(db)
        self.progress_repo = PersonalProgressRepository(db)
        self.settings = get_settings()

    # ---------- 上传 ----------

    async def create_book(
        self, user: User, filename: str, data: bytes
    ) -> tuple[PersonalBook, bool]:
        """上传个人书籍：校验 → 解析（线程池）→ 落盘 → 入库。

        返回 (书籍, 是否命中重复文件)。
        """
        if not data:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "上传文件为空")
        max_bytes = self.settings.PERSONAL_MAX_UPLOAD_MB * 1024 * 1024
        if len(data) > max_bytes:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"文件超过上限 {self.settings.PERSONAL_MAX_UPLOAD_MB}MB",
            )

        sha = hashlib.sha256(data).hexdigest()
        existing = await self.repo.get_by_hash(user.id, sha)
        if existing is not None:
            return existing, True

        count, total_bytes = await self.repo.usage(user.id)
        if count >= self.settings.PERSONAL_MAX_BOOKS_PER_USER:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"个人书籍数量已达上限（{self.settings.PERSONAL_MAX_BOOKS_PER_USER} 本），请先删除不再阅读的书",
            )
        if total_bytes + len(data) > self.settings.PERSONAL_MAX_TOTAL_MB_PER_USER * 1024 * 1024:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"个人书籍存储空间已达上限（{self.settings.PERSONAL_MAX_TOTAL_MB_PER_USER}MB），请先删除旧书",
            )

        # 解析是 CPU/IO 密集型同步逻辑，放线程池，避免阻塞事件循环
        try:
            parsed = await asyncio.to_thread(parse_upload, filename, data)
        except ParseError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

        word_counts = [word_count(body) for _, body in parsed.chapters]
        total_words = sum(word_counts)

        storage_path = await asyncio.to_thread(
            self._store_file, user.id, parsed.source_type, data
        )
        try:
            book = await self.repo.create(
                user_id=user.id,
                title=parsed.title[:255],
                author=parsed.author[:255],
                language=parsed.language[:16],
                source_type=parsed.source_type,
                original_filename=filename.replace("\\", "/").rsplit("/", 1)[-1][:255],
                file_size=len(data),
                content_sha256=sha,
                storage_path=str(storage_path),
                word_count=total_words,
                chapter_count=len(parsed.chapters),
            )
            await self.repo.add_chapters(book.id, parsed.chapters, word_counts)
            await self.db.commit()
            await self.db.refresh(book)
        except Exception:
            await self.db.rollback()
            # 入库失败时清理已落盘文件，避免孤儿文件占用空间
            await asyncio.to_thread(self._remove_file, storage_path)
            raise
        return book, False

    def _store_file(self, user_id: int, source_type: str, data: bytes) -> Path:
        """原始文件落盘：路径由 UUID 生成（不使用用户文件名，杜绝路径穿越）"""
        base = Path(self.settings.PERSONAL_BOOKS_DIR) / str(user_id)
        base.mkdir(parents=True, exist_ok=True)
        target = base / f"{uuid.uuid4().hex}.{source_type}"
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)  # 原子替换，避免半截文件
        return target

    @staticmethod
    def _remove_file(path: Path) -> None:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass  # 文件删除失败不影响数据删除（运维可后续清理）

    # ---------- 查询 ----------

    async def _get_owned(self, user: User, personal_book_id: int) -> PersonalBook:
        book = await self.repo.get_owned(personal_book_id, user.id)
        if book is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "个人书籍不存在或无权访问")
        return book

    async def list_books(self, user: User) -> list[PersonalBookOut]:
        rows = await self.repo.list_by_user(user.id)
        return [PersonalBookOut.model_validate(r) for r in rows]

    async def get_book(self, user: User, personal_book_id: int) -> PersonalBookOut:
        return PersonalBookOut.model_validate(await self._get_owned(user, personal_book_id))

    async def list_chapters(self, user: User, personal_book_id: int) -> list[PersonalChapterOut]:
        await self._get_owned(user, personal_book_id)
        rows = await self.repo.list_chapters(personal_book_id)
        return [PersonalChapterOut.model_validate(r) for r in rows]

    async def get_chapter(
        self, user: User, personal_book_id: int, chapter_index: int
    ) -> PersonalChapterDetailOut:
        book = await self._get_owned(user, personal_book_id)
        row = await self.repo.get_chapter(personal_book_id, chapter_index)
        if row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"书籍「{book.title}」不存在第 {chapter_index} 章",
            )
        return PersonalChapterDetailOut.model_validate(row)

    # ---------- 删除 ----------

    async def delete_book(self, user: User, personal_book_id: int) -> None:
        book = await self._get_owned(user, personal_book_id)
        path = Path(book.storage_path)
        await self.repo.delete(book)          # 章节与进度随外键 CASCADE + 显式删除
        await asyncio.to_thread(self._remove_file, path)

    # ---------- 阅读进度 ----------

    async def get_progress(self, user: User, personal_book_id: int) -> PersonalProgressOut:
        await self._get_owned(user, personal_book_id)
        row = await self.progress_repo.get(user.id, personal_book_id)
        if row is None:
            return PersonalProgressOut(
                personal_book_id=personal_book_id,
                chapter_index=1,
                char_offset=0,
                page_index=0,
                percent=0.0,
                updated_at=datetime.now(timezone.utc),
            )
        return PersonalProgressOut.model_validate(row)

    async def save_progress(
        self, user: User, personal_book_id: int, data: PersonalProgressUpdate
    ) -> PersonalProgressOut:
        book = await self._get_owned(user, personal_book_id)
        chapter = await self.repo.get_chapter(personal_book_id, data.chapter_index)
        if chapter is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"书籍「{book.title}」不存在第 {data.chapter_index} 章，无法保存进度",
            )
        if data.char_offset > len(chapter.content):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"字符偏移 {data.char_offset} 超出章节「{chapter.title}」正文长度 {len(chapter.content)}",
            )
        row = await self.progress_repo.upsert(
            user.id, personal_book_id, data.chapter_index,
            data.char_offset, data.percent, data.page_index,
        )
        return PersonalProgressOut.model_validate(row)


def get_personal_book_service(db: AsyncSession = Depends(get_db)) -> PersonalBookService:
    return PersonalBookService(db)
